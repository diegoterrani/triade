from __future__ import annotations

from datetime import date, datetime, timezone

from daytrade.common.models import Signal
from daytrade.common.risk import RiskLimits, RiskManager
from tests.conftest import sample_instrument


def limits(**overrides) -> RiskLimits:
    values = dict(
        risk_per_trade_pct=0.01,
        max_trades_per_day=2,
        daily_loss_limit_pct=0.02,
        max_drawdown_pct=0.06,
        sticky_drawdown_halt=True,
    )
    values.update(overrides)
    return RiskLimits(**values)


def signal(stop: float | None = 90, side: str = "buy") -> Signal:
    return Signal(
        symbol="AAA",
        ts=datetime(2024, 8, 5, 12, tzinfo=timezone.utc),
        side=side,  # type: ignore[arg-type]
        reason="teste",
        strategy="teste",
        stop_price=stop,
    )


def test_entry_without_stop_is_rejected():
    risk = RiskManager(limits(), equity=10_000)
    decision = risk.approve_entry(signal(None), 10_000, sample_instrument(), 100)
    assert not decision.approved
    assert "stop" in decision.reason


def test_stop_on_the_wrong_side_is_rejected():
    risk = RiskManager(limits(), equity=10_000)
    decision = risk.approve_entry(signal(110), 10_000, sample_instrument(), 100)
    assert decision.reason == "stop do lado errado"


def test_daily_loss_halts_until_the_next_day_only():
    risk = RiskManager(limits(), equity=10_000)
    risk.start_day(date(2024, 8, 5), 10_000)
    reason = risk.update_equity(9_700)
    assert reason == "limite diário de perda"
    assert risk.state.halted
    assert not risk.state.sticky_halt
    blocked = risk.approve_entry(signal(), 9_700, sample_instrument(), 100)
    assert not blocked.approved
    risk.start_day(date(2024, 8, 6), 9_700)
    assert not risk.state.halted
    again = risk.approve_entry(signal(), 9_700, sample_instrument(), 100)
    assert again.approved


def test_drawdown_halt_stays_until_manual_reset():
    risk = RiskManager(limits(), equity=10_000)
    risk.start_day(date(2024, 8, 5), 10_000)
    risk.update_equity(9_200)
    assert risk.state.sticky_halt
    assert risk.state.halt_reason == "drawdown máximo"
    risk.start_day(date(2024, 8, 6), 9_200)
    assert risk.state.halted
    risk.clear_sticky_halt()
    assert not risk.state.halted


def test_max_trades_per_day():
    risk = RiskManager(limits(max_trades_per_day=1), equity=10_000)
    risk.start_day(date(2024, 8, 5), 10_000)
    assert risk.approve_entry(signal(), 10_000, sample_instrument(), 100).approved
    risk.note_entry()
    decision = risk.approve_entry(signal(), 10_000, sample_instrument(), 100)
    assert decision.reason == "máximo de trades no dia"


def test_kill_flag_blocks_even_a_valid_signal():
    risk = RiskManager(limits(), equity=10_000)
    decision = risk.approve_entry(signal(), 10_000, sample_instrument(), 100, kill=True)
    assert decision.reason == "kill switch"


def test_absurd_risk_config_is_refused():
    try:
        RiskLimits(0.5, 1, 0.02, 0.06)
    except ValueError:
        return
    raise AssertionError("risco de 50% por trade não pode passar")
