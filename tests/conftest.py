from __future__ import annotations

from datetime import datetime, timedelta

from daytrade.common.models import Bar, Instrument


def make_bars(symbol: str, start: datetime, rows: list[tuple], step_min: int = 5, timeframe: str = "5m") -> list[Bar]:
    bars = []
    ts = start
    for open_, high, low, close, volume in rows:
        bars.append(Bar(symbol, ts, open_, high, low, close, volume, timeframe))
        ts += timedelta(minutes=step_min)
    return bars


def sample_instrument(**overrides) -> Instrument:
    values = dict(
        symbol="AAA",
        root="AAA",
        tick_size=1,
        point_value=1,
        lot_step=1,
        min_qty=1,
        currency="BRL",
        fee_per_unit_side=0.5,
        slippage_ticks=1,
        max_qty=20,
    )
    values.update(overrides)
    return Instrument(**values)
