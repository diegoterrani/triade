"""Tendência por EMA, stop de ATR e filtro de volatilidade/funding.

Ponto de partida para BTCUSDT e ETHUSDT. Cruzamento não é vantagem estatística
por si só: o filtro existe para ficar de fora quando o mercado está morto, louco
ou com funding extremo. Funding ausente não bloqueia — só bloqueia quando o
número veio e passou do limite.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from daytrade.common.indicators import ATR, EMA, crosses_down, crosses_up
from daytrade.common.models import Bar, Position, Signal


class EmaTrendAtr:
    name = "ema_trend_atr"

    def __init__(
        self,
        *,
        ema_fast: int,
        ema_slow: int,
        atr_period: int,
        atr_mult: float,
        min_atr_pct: float,
        max_atr_pct: float,
        use_funding_filter: bool,
        max_funding_long: float,
        min_funding_short: float,
        funding_blackout_minutes: int,
        timeframe_minutes: int,
        allow_short: bool,
        allow_long: bool = True,
    ) -> None:
        if ema_fast >= ema_slow:
            raise ValueError("ema_fast tem de ser menor que ema_slow")
        if atr_mult <= 0:
            raise ValueError("atr_mult tem de ser positivo")
        self.ema_fast_period = ema_fast
        self.ema_slow_period = ema_slow
        self.atr_period = atr_period
        self.atr_mult = atr_mult
        self.min_atr_pct = min_atr_pct
        self.max_atr_pct = max_atr_pct
        self.use_funding_filter = use_funding_filter
        self.max_funding_long = max_funding_long
        self.min_funding_short = min_funding_short
        self.funding_blackout_minutes = funding_blackout_minutes
        self.timeframe_minutes = timeframe_minutes
        self.allow_short = allow_short
        self.allow_long = allow_long
        self._states: dict[str, _State] = {}

    def reset(self) -> None:
        self._states.clear()

    def describe(self) -> dict[str, object]:
        return {
            "name": self.name,
            "ema_fast": self.ema_fast_period,
            "ema_slow": self.ema_slow_period,
            "atr_period": self.atr_period,
            "atr_mult": self.atr_mult,
            "min_atr_pct": self.min_atr_pct,
            "max_atr_pct": self.max_atr_pct,
            "use_funding_filter": self.use_funding_filter,
            "max_funding_long": self.max_funding_long,
            "min_funding_short": self.min_funding_short,
            "allow_short": self.allow_short,
        }

    def on_bar(self, bar: Bar, position: Position | None) -> list[Signal]:
        state = self._state(bar.symbol)
        prev_fast, prev_slow = state.fast, state.slow
        fast = state.ema_fast.update(bar.close)
        slow = state.ema_slow.update(bar.close)
        atr_value = state.atr.update(bar.high, bar.low, bar.close)
        state.fast, state.slow = fast, slow
        if fast is None or slow is None or prev_fast is None or prev_slow is None or atr_value is None:
            return []
        up = crosses_up(prev_fast, prev_slow, fast, slow)
        down = crosses_down(prev_fast, prev_slow, fast, slow)
        if position is not None and position.qty > 0 and down:
            return [_flat(bar, "EMA rápida cruzou para baixo; saindo da compra")]
        if position is not None and position.qty < 0 and up:
            return [_flat(bar, "EMA rápida cruzou para cima; saindo da venda")]
        if position is not None:
            return []
        if in_funding_blackout(bar.ts, self.timeframe_minutes, self.funding_blackout_minutes):
            return []
        atr_pct = atr_value / bar.close if bar.close else 0.0
        if atr_pct < self.min_atr_pct or atr_pct > self.max_atr_pct:
            return []
        if up and self.allow_long and bar.close > fast and self._funding_allows("buy", bar.funding_rate):
            return [
                Signal(
                    symbol=bar.symbol,
                    ts=bar.ts,
                    side="buy",
                    reason="cruzamento de EMA para cima dentro da banda de ATR e do funding",
                    strategy=self.name,
                    stop_price=bar.close - self.atr_mult * atr_value,
                )
            ]
        if down and self.allow_short and bar.close < fast and self._funding_allows("sell", bar.funding_rate):
            return [
                Signal(
                    symbol=bar.symbol,
                    ts=bar.ts,
                    side="sell",
                    reason="cruzamento de EMA para baixo dentro da banda de ATR e do funding",
                    strategy=self.name,
                    stop_price=bar.close + self.atr_mult * atr_value,
                )
            ]
        return []

    def _funding_allows(self, side: str, funding: float | None) -> bool:
        if not self.use_funding_filter or funding is None:
            return True
        if side == "buy" and funding > self.max_funding_long:
            return False
        if side == "sell" and funding < self.min_funding_short:
            return False
        return True

    def _state(self, symbol: str) -> _State:
        state = self._states.get(symbol)
        if state is None:
            state = _State(EMA(self.ema_fast_period), EMA(self.ema_slow_period), ATR(self.atr_period))
            self._states[symbol] = state
        return state


def in_funding_blackout(ts: datetime, timeframe_minutes: int, pad_minutes: int) -> bool:
    if pad_minutes < 0:
        return False
    moment = ts.astimezone(timezone.utc)
    start = moment - timedelta(minutes=pad_minutes)
    end = moment + timedelta(minutes=timeframe_minutes + pad_minutes)
    for hour in (0, 8, 16):
        stamp = moment.replace(hour=hour, minute=0, second=0, microsecond=0)
        for candidate in (stamp - timedelta(days=1), stamp, stamp + timedelta(days=1)):
            if start <= candidate < end:
                return True
    return False


def _flat(bar: Bar, reason: str) -> Signal:
    return Signal(symbol=bar.symbol, ts=bar.ts, side="flat", reason=reason, strategy="ema_trend_atr", immediate=False)


@dataclass
class _State:
    ema_fast: EMA
    ema_slow: EMA
    atr: ATR
    fast: float | None = None
    slow: float | None = None


def build_strategy(cfg: dict) -> EmaTrendAtr:
    params = cfg["strategy"]
    market = cfg.get("market", "usdm")
    allow_short = bool(params.get("allow_short", market == "usdm"))
    if market == "spot":
        allow_short = False
    timeframe = str(cfg.get("feed", {}).get("timeframe", "15m"))
    minutes = int(timeframe[:-1]) * (60 if timeframe.endswith("h") else 1)
    return EmaTrendAtr(
        ema_fast=int(params["ema_fast"]),
        ema_slow=int(params["ema_slow"]),
        atr_period=int(params["atr_period"]),
        atr_mult=float(params["atr_mult"]),
        min_atr_pct=float(params["min_atr_pct"]),
        max_atr_pct=float(params["max_atr_pct"]),
        use_funding_filter=bool(params.get("use_funding_filter", True)) and market == "usdm",
        max_funding_long=float(params.get("max_funding_long", 0.0005)),
        min_funding_short=float(params.get("min_funding_short", -0.0005)),
        funding_blackout_minutes=int(params.get("funding_blackout_minutes", 5)),
        timeframe_minutes=minutes,
        allow_short=allow_short,
        allow_long=bool(params.get("allow_long", True)),
    )


def build_strategies(cfg: dict) -> dict[str, EmaTrendAtr]:
    strategy = build_strategy(cfg)
    return {spec["symbol"]: strategy for spec in cfg["symbols"]}
