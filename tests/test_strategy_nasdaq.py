from __future__ import annotations

from datetime import date, datetime, time
from zoneinfo import ZoneInfo

from daytrade.common.models import Position
from daytrade.nasdaq.calendar import early_close, is_nyse_holiday, thanksgiving
from daytrade.nasdaq.strategy import VwapMeanReversion, build_strategy, mean_reversion_side
from tests.conftest import make_bars

NY = ZoneInfo("America/New_York")


def test_mean_reversion_side_requires_a_flat_trend_and_an_arm():
    assert mean_reversion_side(2.0, 1.5, True, True) == "sell"
    assert mean_reversion_side(-2.0, 1.5, True, True) == "buy"
    assert mean_reversion_side(2.0, 1.5, False, True) is None
    assert mean_reversion_side(2.0, 1.5, True, False) is None


def test_mode_switch_changes_the_strategy():
    base = {
        "timezone": "America/New_York",
        "calendar": {},
        "news_blackouts": [],
        "strategy": {
            "name": "ny_open_range",
            "range_start": "09:30",
            "orb_minutes": 30,
            "flatten_time": "15:45",
            "no_new_trades_after": "15:15",
            "ema_fast": 2,
            "ema_slow": 4,
            "atr_period": 2,
            "atr_mult": 1.5,
            "extension_k": 1.5,
            "rearm_k": 0.5,
            "slope_max": 0.01,
            "mr_atr_mult": 1.0,
            "entries_after": "10:00",
        },
    }
    assert build_strategy(base).name == "ny_open_range"
    other = {**base, "strategy": {**base["strategy"], "name": "vwap_mean_reversion"}}
    assert build_strategy(other).name == "vwap_mean_reversion"


def test_holiday_flattens():
    strategy = VwapMeanReversion(
        tz=NY,
        entries_after=time(10, 0),
        flatten_time=time(15, 45),
        no_new_trades_after=time(15, 15),
        ema_fast=2,
        ema_slow=4,
        atr_period=2,
        extension_k=1.5,
        rearm_k=0.5,
        slope_max=0.01,
        atr_mult=1,
        is_holiday=lambda _day: True,
    )
    start = datetime(2024, 11, 28, 12, 0, tzinfo=NY)
    bar = make_bars("USTEC", start, [(100, 101, 99, 100, 10)])[0]
    position = Position(
        symbol="USTEC",
        qty=1,
        avg_price=100,
        stop_price=90,
        opened_at=start,
        strategy="vwap_mean_reversion",
        entry_reason="teste",
        entry_fee=0,
        contract="USTEC",
        client_order_id="x",
    )
    assert strategy.on_bar(bar, position)[0].side == "flat"
    assert strategy.on_bar(bar, None) == []


def test_known_us_calendar_dates():
    assert thanksgiving(2024) == date(2024, 11, 28)
    assert is_nyse_holiday(date(2024, 11, 28))
    assert is_nyse_holiday(date(2024, 3, 29))  # Sexta-feira Santa
    assert early_close(date(2024, 11, 29)) == time(13, 0)
    assert early_close(date(2024, 12, 24)) == time(13, 0)
    assert not is_nyse_holiday(date(2024, 11, 27))
