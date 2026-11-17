"""Rompimento da abertura com VWAP, tendência e stop de ATR.

Ponto de partida configurável. O filtro existe para reduzir operação, não para
garantir acerto. A ordem só nasce depois que a janela da abertura fecha, e o
preenchimento fica para a barra seguinte (quem chama a estratégia decide isso
pelo campo `immediate`).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, time
from typing import Callable
from zoneinfo import ZoneInfo

from daytrade.common.indicators import ATR, EMA
from daytrade.common.models import Bar, Position, Signal
from daytrade.common.sessions import add_minutes, in_half_open, local_clock


@dataclass
class _State:
    ema_fast: EMA
    ema_slow: EMA
    atr: ATR
    day: date | None = None
    vwap_pv: float = 0.0
    vwap_v: float = 0.0
    vwap: float | None = None
    range_high: float | None = None
    range_low: float | None = None
    range_ready: bool = False
    traded: bool = False
    fast: float | None = None
    slow: float | None = None
    atr_value: float | None = None


class OpeningRangeBreakout:
    name = "orb_vwap_trend"

    def __init__(
        self,
        *,
        tz: ZoneInfo,
        range_start: time,
        orb_minutes: int,
        flatten_time: time,
        no_new_trades_after: time,
        ema_fast: int,
        ema_slow: int,
        atr_period: int,
        atr_mult: float,
        use_vwap_filter: bool = True,
        use_trend_filter: bool = True,
        one_trade_per_day: bool = True,
        allow_long: bool = True,
        allow_short: bool = True,
        blackouts: list[tuple[time, time]] | None = None,
        blackouts_by_symbol: dict[str, list[tuple[time, time]]] | None = None,
        flatten_by_symbol: dict[str, time] | None = None,
        no_new_by_symbol: dict[str, time] | None = None,
        is_holiday: Callable[[date], bool] | None = None,
        flatten_time_on: Callable[[str, date], time] | None = None,
        name: str | None = None,
    ) -> None:
        if ema_fast >= ema_slow:
            raise ValueError("ema_fast tem de ser menor que ema_slow")
        if orb_minutes < 5:
            raise ValueError("orb_minutes tem de ser >= 5")
        if atr_mult <= 0:
            raise ValueError("atr_mult tem de ser positivo")
        self.tz = tz
        self.range_start = range_start
        self.range_end = add_minutes(range_start, orb_minutes)
        self.orb_minutes = orb_minutes
        self.flatten_time = flatten_time
        self.no_new_trades_after = no_new_trades_after
        self.ema_fast_period = ema_fast
        self.ema_slow_period = ema_slow
        self.atr_period = atr_period
        self.atr_mult = atr_mult
        self.use_vwap_filter = use_vwap_filter
        self.use_trend_filter = use_trend_filter
        self.one_trade_per_day = one_trade_per_day
        self.allow_long = allow_long
        self.allow_short = allow_short
        self.blackouts = list(blackouts or [])
        self.blackouts_by_symbol = blackouts_by_symbol or {}
        self.flatten_by_symbol = flatten_by_symbol or {}
        self.no_new_by_symbol = no_new_by_symbol or {}
        self.is_holiday = is_holiday
        self.flatten_time_on = flatten_time_on
        if name:
            self.name = name
        self._states: dict[str, _State] = {}

    def reset(self) -> None:
        self._states.clear()

    def describe(self) -> dict[str, object]:
        return {
            "name": self.name,
            "range_start": self.range_start.strftime("%H:%M"),
            "range_end": self.range_end.strftime("%H:%M"),
            "orb_minutes": self.orb_minutes,
            "ema_fast": self.ema_fast_period,
            "ema_slow": self.ema_slow_period,
            "atr_period": self.atr_period,
            "atr_mult": self.atr_mult,
            "use_vwap_filter": self.use_vwap_filter,
            "use_trend_filter": self.use_trend_filter,
            "one_trade_per_day": self.one_trade_per_day,
        }

    def on_bar(self, bar: Bar, position: Position | None) -> list[Signal]:
        state = self._state(bar.symbol)
        day, clock = local_clock(bar.ts, self.tz)
        self._roll_day(state, day)
        self._update_indicators(state, bar)
        if self.is_holiday and self.is_holiday(day):
            if position is not None:
                return [self._flat(bar, "feriado; zerando")]
            return []
        flatten_at = self._flatten_at(bar.symbol, day)
        if position is not None and clock >= flatten_at:
            return [self._flat(bar, f"zeragem antes do fim da sessão ({flatten_at.strftime('%H:%M')})")]
        if position is not None:
            return []
        if clock < self.range_end or not state.range_ready:
            return []
        if self.one_trade_per_day and state.traded:
            return []
        if clock >= self._no_new_at(bar.symbol):
            return []
        if self._in_blackout(bar.symbol, clock):
            return []
        if state.atr_value is None or state.atr_value <= 0:
            return []
        if self.use_trend_filter and (state.fast is None or state.slow is None):
            return []
        stop_distance = self.atr_mult * state.atr_value
        long_ok = bar.close > (state.range_high or bar.close)
        short_ok = bar.close < (state.range_low or bar.close)
        if self.use_vwap_filter and state.vwap is not None:
            long_ok = long_ok and bar.close > state.vwap
            short_ok = short_ok and bar.close < state.vwap
        if self.use_trend_filter and state.fast is not None and state.slow is not None:
            long_ok = long_ok and state.fast > state.slow
            short_ok = short_ok and state.fast < state.slow
        if long_ok and self.allow_long and state.range_high is not None:
            state.traded = True
            return [
                Signal(
                    symbol=bar.symbol,
                    ts=bar.ts,
                    side="buy",
                    reason=self._reason("máxima", "acima"),
                    strategy=self.name,
                    stop_price=bar.close - stop_distance,
                )
            ]
        if short_ok and self.allow_short and state.range_low is not None:
            state.traded = True
            return [
                Signal(
                    symbol=bar.symbol,
                    ts=bar.ts,
                    side="sell",
                    reason=self._reason("mínima", "abaixo"),
                    strategy=self.name,
                    stop_price=bar.close + stop_distance,
                )
            ]
        return []

    def _reason(self, extreme: str, side_word: str) -> str:
        parts = [f"rompimento da {extreme} da abertura"]
        if self.use_vwap_filter:
            parts.append(f"preço {side_word} da VWAP")
        if self.use_trend_filter:
            parts.append("filtro de tendência por EMA")
        parts.append(f"stop de {self.atr_mult:g} ATR")
        return "; ".join(parts)

    def _state(self, symbol: str) -> _State:
        state = self._states.get(symbol)
        if state is None:
            state = _State(
                ema_fast=EMA(self.ema_fast_period),
                ema_slow=EMA(self.ema_slow_period),
                atr=ATR(self.atr_period),
            )
            self._states[symbol] = state
        return state

    def _roll_day(self, state: _State, day: date) -> None:
        if state.day == day:
            return
        state.day = day
        state.vwap_pv = 0.0
        state.vwap_v = 0.0
        state.vwap = None
        state.range_high = None
        state.range_low = None
        state.range_ready = False
        state.traded = False

    def _update_indicators(self, state: _State, bar: Bar) -> None:
        state.fast = state.ema_fast.update(bar.close)
        state.slow = state.ema_slow.update(bar.close)
        state.atr_value = state.atr.update(bar.high, bar.low, bar.close)
        typical = (bar.high + bar.low + bar.close) / 3
        volume = bar.volume if bar.volume > 0 else 1.0
        state.vwap_pv += typical * volume
        state.vwap_v += volume
        state.vwap = state.vwap_pv / state.vwap_v
        _, clock = local_clock(bar.ts, self.tz)
        if in_half_open(clock, self.range_start, self.range_end):
            state.range_high = bar.high if state.range_high is None else max(state.range_high, bar.high)
            state.range_low = bar.low if state.range_low is None else min(state.range_low, bar.low)
        if clock >= self.range_end and state.range_high is not None and state.range_low is not None:
            state.range_ready = True

    def _flatten_at(self, symbol: str, day: date) -> time:
        if self.flatten_time_on is not None:
            return self.flatten_time_on(symbol, day)
        return self.flatten_by_symbol.get(symbol, self.flatten_time)

    def _no_new_at(self, symbol: str) -> time:
        return self.no_new_by_symbol.get(symbol, self.no_new_trades_after)

    def _in_blackout(self, symbol: str, clock: time) -> bool:
        windows = list(self.blackouts) + list(self.blackouts_by_symbol.get(symbol, []))
        return any(in_half_open(clock, start, end) for start, end in windows)

    def _flat(self, bar: Bar, reason: str) -> Signal:
        return Signal(
            symbol=bar.symbol,
            ts=bar.ts,
            side="flat",
            reason=reason,
            strategy=self.name,
            immediate=True,
        )
