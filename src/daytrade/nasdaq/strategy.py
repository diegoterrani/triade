"""Estratégias do NASDAQ: rompimento da abertura de Nova York ou reversão à VWAP.

O modo sai do config. As duas implementam o mesmo protocolo, então a execução
não sabe qual está ligada.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, time
from typing import Callable
from zoneinfo import ZoneInfo

from daytrade.common.indicators import ATR, EMA
from daytrade.common.models import Bar, Position, Signal
from daytrade.common.sessions import add_minutes, in_half_open, local_clock, parse_hhmm
from daytrade.common.strategies import OpeningRangeBreakout
from daytrade.nasdaq.calendar import early_close, session_checker


def _windows(raw: list | None) -> list[tuple[time, time]]:
    return [(parse_hhmm(start), parse_hhmm(end)) for start, end in (raw or [])]


class VwapMeanReversion:
    """Fade quando o preço estica da VWAP e a tendência de EMA está plana.

    Alvo é a VWAP do momento do sinal. Stop é um múltiplo do ATR além da entrada.
    Não opera tendência forte: se as EMAs estão afastadas, o sinal não sai.
    """

    name = "vwap_mean_reversion"

    def __init__(
        self,
        *,
        tz: ZoneInfo,
        entries_after: time,
        flatten_time: time,
        no_new_trades_after: time,
        ema_fast: int,
        ema_slow: int,
        atr_period: int,
        extension_k: float,
        rearm_k: float,
        slope_max: float,
        atr_mult: float,
        blackouts: list[tuple[time, time]] | None = None,
        is_holiday: Callable[[date], bool] | None = None,
        flatten_time_on: Callable[[str, date], time] | None = None,
    ) -> None:
        if extension_k <= 0 or atr_mult <= 0:
            raise ValueError("extension_k e atr_mult têm de ser positivos")
        self.tz = tz
        self.entries_after = entries_after
        self.flatten_time = flatten_time
        self.no_new_trades_after = no_new_trades_after
        self.ema_fast_period = ema_fast
        self.ema_slow_period = ema_slow
        self.atr_period = atr_period
        self.extension_k = extension_k
        self.rearm_k = rearm_k
        self.slope_max = slope_max
        self.atr_mult = atr_mult
        self.blackouts = list(blackouts or [])
        self.is_holiday = is_holiday
        self.flatten_time_on = flatten_time_on
        self._states: dict[str, _State] = {}

    def reset(self) -> None:
        self._states.clear()

    def describe(self) -> dict[str, object]:
        return {
            "name": self.name,
            "entries_after": self.entries_after.strftime("%H:%M"),
            "extension_k": self.extension_k,
            "rearm_k": self.rearm_k,
            "slope_max": self.slope_max,
            "atr_mult": self.atr_mult,
            "ema_fast": self.ema_fast_period,
            "ema_slow": self.ema_slow_period,
        }

    def on_bar(self, bar: Bar, position: Position | None) -> list[Signal]:
        state = self._state(bar.symbol)
        day, clock = local_clock(bar.ts, self.tz)
        self._roll_day(state, day)
        fast = state.ema_fast.update(bar.close)
        slow = state.ema_slow.update(bar.close)
        atr_value = state.atr.update(bar.high, bar.low, bar.close)
        state.vwap = _accumulate_vwap(state, bar)
        if self.is_holiday and self.is_holiday(day):
            if position is not None:
                return [_flat(bar, self.name, "feriado nos EUA; zerando")]
            return []
        flatten_at = self.flatten_time_on(bar.symbol, day) if self.flatten_time_on else self.flatten_time
        if position is not None and clock >= flatten_at:
            return [_flat(bar, self.name, f"zeragem da sessão de Nova York ({flatten_at.strftime('%H:%M')})")]
        if position is not None or fast is None or slow is None or atr_value is None or atr_value <= 0:
            return []
        if clock < self.entries_after or clock >= self.no_new_trades_after:
            return []
        if any(in_half_open(clock, start, end) for start, end in self.blackouts):
            return []
        extension = (bar.close - state.vwap) / atr_value
        if abs(extension) <= self.rearm_k:
            state.armed = True
        flat_trend = abs(fast - slow) / bar.close <= self.slope_max
        side = mean_reversion_side(extension, self.extension_k, flat_trend, state.armed)
        if side is None:
            return []
        state.armed = False
        if side == "sell":
            stop = bar.close + self.atr_mult * atr_value
            reason = "preço esticado acima da VWAP com EMAs planas; venda de volta à média"
        else:
            stop = bar.close - self.atr_mult * atr_value
            reason = "preço esticado abaixo da VWAP com EMAs planas; compra de volta à média"
        return [
            Signal(
                symbol=bar.symbol,
                ts=bar.ts,
                side=side,  # type: ignore[arg-type]
                reason=reason,
                strategy=self.name,
                stop_price=stop,
                target_price=state.vwap,
            )
        ]

    def _state(self, symbol: str) -> _State:
        state = self._states.get(symbol)
        if state is None:
            state = _State(EMA(self.ema_fast_period), EMA(self.ema_slow_period), ATR(self.atr_period))
            self._states[symbol] = state
        return state

    def _roll_day(self, state: _State, day: date) -> None:
        if state.day == day:
            return
        state.day = day
        state.vwap_pv = 0.0
        state.vwap_v = 0.0
        state.vwap = None
        state.armed = True


def mean_reversion_side(extension: float, k: float, flat_trend: bool, armed: bool) -> str | None:
    if not armed or not flat_trend:
        return None
    if extension >= k:
        return "sell"
    if extension <= -k:
        return "buy"
    return None


@dataclass
class _State:
    ema_fast: EMA
    ema_slow: EMA
    atr: ATR
    day: date | None = None
    vwap_pv: float = 0.0
    vwap_v: float = 0.0
    vwap: float | None = None
    armed: bool = True


def _accumulate_vwap(state: _State, bar: Bar) -> float:
    typical = (bar.high + bar.low + bar.close) / 3
    volume = bar.volume if bar.volume > 0 else 1.0
    state.vwap_pv += typical * volume
    state.vwap_v += volume
    return state.vwap_pv / state.vwap_v


def _flat(bar: Bar, name: str, reason: str) -> Signal:
    return Signal(symbol=bar.symbol, ts=bar.ts, side="flat", reason=reason, strategy=name, immediate=True)


def _flatten_time_on(default: time):
    def resolve(_symbol: str, day: date) -> time:
        early = early_close(day)
        if early is None:
            return default
        earlier = add_minutes(early, -15)
        return earlier if earlier < default else default

    return resolve


def build_strategy(cfg: dict):
    params = cfg["strategy"]
    name = params.get("name", "ny_open_range")
    tz = ZoneInfo(cfg["timezone"])
    calendar_cfg = cfg.get("calendar") or {}
    is_session = session_checker(calendar_cfg.get("extra_closed"), calendar_cfg.get("extra_open"))
    blackouts = _windows(cfg.get("news_blackouts"))
    holiday = lambda day: not is_session(day)  # noqa: E731
    if name in ("ny_open_range", "orb"):
        return OpeningRangeBreakout(
            name="ny_open_range",
            tz=tz,
            range_start=parse_hhmm(params["range_start"]),
            orb_minutes=int(params["orb_minutes"]),
            flatten_time=parse_hhmm(params["flatten_time"]),
            no_new_trades_after=parse_hhmm(params["no_new_trades_after"]),
            ema_fast=int(params["ema_fast"]),
            ema_slow=int(params["ema_slow"]),
            atr_period=int(params["atr_period"]),
            atr_mult=float(params["atr_mult"]),
            use_vwap_filter=bool(params.get("use_vwap_filter", True)),
            use_trend_filter=bool(params.get("use_trend_filter", True)),
            one_trade_per_day=bool(params.get("one_trade_per_day", True)),
            blackouts=blackouts,
            is_holiday=holiday,
            flatten_time_on=_flatten_time_on(parse_hhmm(params["flatten_time"])),
        )
    if name in ("vwap_mean_reversion", "vwap_mr"):
        return VwapMeanReversion(
            tz=tz,
            entries_after=parse_hhmm(params.get("entries_after", params["range_start"])),
            flatten_time=parse_hhmm(params["flatten_time"]),
            no_new_trades_after=parse_hhmm(params["no_new_trades_after"]),
            ema_fast=int(params["ema_fast"]),
            ema_slow=int(params["ema_slow"]),
            atr_period=int(params["atr_period"]),
            extension_k=float(params.get("extension_k", 1.5)),
            rearm_k=float(params.get("rearm_k", 0.5)),
            slope_max=float(params.get("slope_max", 0.0015)),
            atr_mult=float(params.get("mr_atr_mult", 1.0)),
            blackouts=blackouts,
            is_holiday=holiday,
            flatten_time_on=_flatten_time_on(parse_hhmm(params["flatten_time"])),
        )
    raise ValueError("estratégia desconhecida. Use ny_open_range ou vwap_mean_reversion.")


def build_strategies(cfg: dict) -> dict:
    strategy = build_strategy(cfg)
    return {spec["symbol"]: strategy for spec in cfg["symbols"]}
