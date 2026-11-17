from __future__ import annotations

from datetime import datetime, timedelta, timezone

from daytrade.crypto.strategy import EmaTrendAtr, in_funding_blackout
from tests.conftest import make_bars


def _strategy(**overrides) -> EmaTrendAtr:
    values = dict(
        ema_fast=2,
        ema_slow=4,
        atr_period=2,
        atr_mult=2.0,
        min_atr_pct=0.0,
        max_atr_pct=1.0,
        use_funding_filter=True,
        max_funding_long=0.0005,
        min_funding_short=-0.0005,
        funding_blackout_minutes=5,
        timeframe_minutes=15,
        allow_short=True,
    )
    values.update(overrides)
    return EmaTrendAtr(**values)


def _path(funding: float | None):
    start = datetime(2024, 8, 5, 12, 0, tzinfo=timezone.utc)
    flat = [(10, 10.2, 9.8, 10, 1)] * 6
    jump = []
    price = 10
    for _ in range(6):
        price += 1
        jump.append((price - 1, price + 0.2, price - 1.1, price, 1))
    bars = make_bars("BTCUSDT", start, flat + jump, step_min=15, timeframe="15m")
    if funding is None:
        return bars
    return [
        type(bar)(
            symbol=bar.symbol,
            ts=bar.ts,
            open=bar.open,
            high=bar.high,
            low=bar.low,
            close=bar.close,
            volume=bar.volume,
            timeframe=bar.timeframe,
            funding_rate=funding,
        )
        for bar in bars
    ]


def test_ema_cross_emits_a_long_with_stop():
    strategy = _strategy()
    signals = []
    for bar in _path(None):
        signals.extend(strategy.on_bar(bar, None))
    buys = [item for item in signals if item.side == "buy"]
    assert buys
    assert buys[0].stop_price < 20
    assert "ATR" in buys[0].reason or "funding" in buys[0].reason


def test_extreme_funding_blocks_the_long():
    strategy = _strategy()
    signals = []
    for bar in _path(0.01):
        signals.extend(strategy.on_bar(bar, None))
    assert [item for item in signals if item.side == "buy"] == []


def test_spot_does_not_short():
    from daytrade.crypto.strategy import build_strategy

    strategy = build_strategy(
        {
            "market": "spot",
            "feed": {"timeframe": "15m"},
            "strategy": {
                "ema_fast": 2,
                "ema_slow": 4,
                "atr_period": 2,
                "atr_mult": 2,
                "min_atr_pct": 0,
                "max_atr_pct": 1,
                "allow_short": True,
                "use_funding_filter": False,
            },
        }
    )
    assert strategy.allow_short is False


def test_funding_window_blocks_the_settlement_bar():
    stamp = datetime(2024, 8, 5, 0, 0, tzinfo=timezone.utc)
    assert in_funding_blackout(stamp, 15, 5)
    assert not in_funding_blackout(stamp + timedelta(hours=3), 15, 5)
