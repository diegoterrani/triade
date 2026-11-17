from __future__ import annotations

from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from daytrade.common.models import Position
from daytrade.common.strategies import OpeningRangeBreakout
from tests.conftest import make_bars

TZ = ZoneInfo("America/Sao_Paulo")


def strategy(**overrides) -> OpeningRangeBreakout:
    values = dict(
        tz=TZ,
        range_start=time(9, 0),
        orb_minutes=15,
        flatten_time=time(18, 10),
        no_new_trades_after=time(17, 40),
        ema_fast=2,
        ema_slow=4,
        atr_period=2,
        atr_mult=1.5,
        use_vwap_filter=True,
        use_trend_filter=True,
    )
    values.update(overrides)
    return OpeningRangeBreakout(**values)


def session_bars(start_price: float, step: float, count: int = 12):
    start = datetime(2024, 8, 5, 9, 0, tzinfo=TZ)
    rows = []
    price = start_price
    for _ in range(count):
        close = price + step
        rows.append((price, max(price, close) + 0.4, min(price, close) - 0.4, close, 1000))
        price = close
    return make_bars("WIN", start, rows)


def test_breakout_long_has_stop_and_reason():
    orb = strategy()
    signals = []
    for bar in session_bars(100, 1.0):
        signals.extend(orb.on_bar(bar, None))
    buys = [item for item in signals if item.side == "buy"]
    assert buys
    assert buys[0].stop_price is not None
    assert 50 < buys[0].stop_price < 130
    assert "VWAP" in buys[0].reason
    assert "EMA" in buys[0].reason
    assert buys[0].immediate is False


def test_breakout_short_on_a_falling_open():
    orb = strategy()
    signals = []
    for bar in session_bars(100, -1.0):
        signals.extend(orb.on_bar(bar, None))
    sells = [item for item in signals if item.side == "sell"]
    assert sells
    assert sells[0].stop_price > 50


def test_no_signal_before_the_range_closes():
    orb = strategy()
    bars = session_bars(100, 1.0)[:3]
    signals = []
    for bar in bars:
        signals.extend(orb.on_bar(bar, None))
    assert signals == []


def test_blackout_blocks_the_entry():
    orb = strategy(blackouts=[(time(9, 15), time(18, 0))])
    signals = []
    for bar in session_bars(100, 1.0):
        signals.extend(orb.on_bar(bar, None))
    assert [item for item in signals if item.side == "buy"] == []


def test_holiday_flattens_and_does_not_open():
    orb = strategy(is_holiday=lambda _day: True)
    start = datetime(2024, 8, 5, 12, 0, tzinfo=TZ)
    bar = make_bars("WIN", start, [(100, 110, 90, 105, 10)])[0]
    position = Position(
        symbol="WIN",
        qty=1,
        avg_price=100,
        stop_price=90,
        opened_at=start,
        strategy="orb_vwap_trend",
        entry_reason="teste",
        entry_fee=0,
        contract="WINQ24",
        client_order_id="x",
    )
    flat = orb.on_bar(bar, position)
    assert flat[0].side == "flat"
    assert flat[0].immediate
    assert orb.on_bar(bar, None) == []


def test_flatten_before_the_close():
    orb = strategy(flatten_time=time(12, 0))
    start = datetime(2024, 8, 5, 12, 0, tzinfo=TZ)
    bar = make_bars("WIN", start, [(100, 101, 99, 100, 10)])[0]
    position = Position(
        symbol="WIN",
        qty=-1,
        avg_price=100,
        stop_price=110,
        opened_at=start - timedelta(hours=1),
        strategy="orb_vwap_trend",
        entry_reason="teste",
        entry_fee=0,
        contract="WINQ24",
        client_order_id="x",
    )
    assert orb.on_bar(bar, position)[0].reason.startswith("zeragem")
