from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from daytrade.common.broker_paper import PaperBroker
from daytrade.common.errors import SafetyError
from daytrade.common.execution import ExecutionEngine
from daytrade.common.ids import client_order_id
from daytrade.common.journal import Journal
from daytrade.common.killswitch import KillSwitch
from daytrade.common.models import OrderRequest, Signal
from daytrade.common.prices import net_pnl
from daytrade.common.reconcile import reconcile
from daytrade.common.risk import RiskLimits, RiskManager
from tests.conftest import make_bars, sample_instrument


class Scripted:
    name = "scripted"

    def __init__(self, plan: list[list[Signal]]):
        self.plan = list(plan)

    def reset(self) -> None:
        return None

    def describe(self) -> dict:
        return {"name": self.name}

    def on_bar(self, bar, position):
        if not self.plan:
            return []
        return self.plan.pop(0)


def build(tmp_path, instrument, strategy, equity=10_000, kill_root=None):
    broker = PaperBroker({instrument.symbol: instrument}, equity)
    risk = RiskManager(
        RiskLimits(0.01, 5, 0.05, 0.20, sticky_drawdown_halt=True),
        equity=equity,
    )
    kill = KillSwitch("t", kill_root) if kill_root is not None else None
    engine = ExecutionEngine(
        agent="t",
        broker=broker,
        risk=risk,
        instruments={instrument.symbol: instrument},
        strategies={instrument.symbol: strategy},
        journal=Journal(tmp_path / "journal.jsonl"),
        risk_tz=timezone.utc,
        kill=kill,
    )
    return engine


def test_stop_slippage_and_fees(tmp_path):
    inst = sample_instrument()
    start = datetime(2024, 8, 5, 12, tzinfo=timezone.utc)
    bars = make_bars(
        "AAA",
        start,
        [
            (100, 110, 99, 108, 1000),
            (100, 105, 80, 82, 1000),
        ],
    )
    signal = Signal("AAA", bars[0].ts, "buy", "teste de stop", "scripted", stop_price=90)
    engine = build(tmp_path, inst, Scripted([[signal], []]))
    engine.process_bar(bars[0])
    engine.process_bar(bars[1])
    assert len(engine.trades) == 1
    trade = engine.trades[0]
    assert trade.entry_price == 101
    assert trade.exit_price == 89
    assert trade.qty == 9
    assert trade.fees == pytest.approx(9)
    assert trade.pnl == pytest.approx(net_pnl(9, 101, 89, 1, 4.5, 4.5))
    assert trade.exit_reason == "stop"
    assert engine.positions == {}


def test_same_client_id_does_not_double_fill(tmp_path):
    inst = sample_instrument(fee_per_unit_side=0)
    broker = PaperBroker({"AAA": inst}, 10_000)
    order = OrderRequest(
        client_order_id="abc",
        symbol="AAA",
        side="buy",
        qty=1,
        reason="teste",
        strategy="scripted",
        ts=datetime(2024, 8, 5, tzinfo=timezone.utc),
        stop_price=90,
    )
    first = broker.submit(order, 100)
    cash = broker.cash
    second = broker.submit(order, 100)
    assert first == second
    assert broker.cash == cash
    assert broker.positions()["AAA"] == 1


def test_entry_without_stop_never_reaches_the_book(tmp_path):
    inst = sample_instrument()
    broker = PaperBroker({"AAA": inst}, 10_000)
    order = OrderRequest(
        "sem-stop",
        "AAA",
        "buy",
        1,
        "teste",
        "scripted",
        datetime(2024, 8, 5, tzinfo=timezone.utc),
        stop_price=None,
    )
    with pytest.raises(SafetyError):
        broker.submit(order, 100)


def test_gap_through_the_stop_skips_the_entry(tmp_path):
    inst = sample_instrument()
    start = datetime(2024, 8, 5, 12, tzinfo=timezone.utc)
    bars = make_bars("AAA", start, [(100, 101, 99, 100, 1), (80, 82, 70, 75, 1)])
    signal = Signal("AAA", bars[0].ts, "buy", "gap", "scripted", stop_price=90)
    engine = build(tmp_path, inst, Scripted([[signal], []]))
    engine.process_bar(bars[0])
    engine.process_bar(bars[1])
    assert engine.trades == []
    assert engine.positions == {}


def test_disconnect_drops_the_pending_signal(tmp_path):
    inst = sample_instrument()
    start = datetime(2024, 8, 5, 12, tzinfo=timezone.utc)
    bars = make_bars("AAA", start, [(100, 101, 99, 100, 1), (100, 110, 99, 108, 1)])
    signal = Signal("AAA", bars[0].ts, "buy", "pendente", "scripted", stop_price=90)
    engine = build(tmp_path, inst, Scripted([[signal], []]))
    engine.process_bar(bars[0])
    assert "AAA" in engine.pending
    engine.on_disconnect("queda de rede")
    engine.process_bar(bars[1])
    assert engine.positions == {}
    assert engine.block_entries


def test_reconcile_adopts_and_blocks_new_entries(tmp_path):
    inst = sample_instrument()
    start = datetime(2024, 8, 5, 12, tzinfo=timezone.utc)
    bars = make_bars("AAA", start, [(100, 101, 99, 100, 1), (100, 110, 99.5, 108, 1)])
    engine = build(tmp_path, inst, Scripted([[], []]))
    engine.process_bar(bars[0])
    engine.broker.mark("AAA", 100)
    engine.broker.force_qty("AAA", 2)
    result = engine.reconcile_and_adopt()
    assert not result.ok
    assert "AAA" in result.adopted
    assert engine.block_entries
    assert engine.positions["AAA"].stop_price < 100
    later = Signal("AAA", bars[1].ts, "buy", "não pode", "scripted", stop_price=90)
    engine.strategies["AAA"] = Scripted([[later]])
    engine.process_bar(bars[1])
    assert engine.positions["AAA"].qty == 2


def test_kill_switch_flattens(tmp_path):
    inst = sample_instrument(fee_per_unit_side=0)
    root = tmp_path / "var"
    start = datetime(2024, 8, 5, 12, tzinfo=timezone.utc)
    bars = make_bars(
        "AAA",
        start,
        [
            (100, 110, 99, 108, 1),
            (100, 110, 99, 108, 1),
            (108, 112, 107, 111, 1),
        ],
    )
    signal = Signal("AAA", bars[0].ts, "buy", "entra", "scripted", stop_price=90)
    engine = build(tmp_path, inst, Scripted([[signal], [], []]), kill_root=root)
    engine.process_bar(bars[0])
    engine.process_bar(bars[1])
    assert engine.positions["AAA"].qty > 0
    engine.kill.trip("teste")
    assert engine.process_bar(bars[2]) == "kill"
    assert engine.positions == {}
    assert engine.broker.positions() == {}


def test_client_order_id_is_stable_and_safe():
    ts = datetime(2024, 8, 5, 15, 30, tzinfo=timezone.utc)
    first = client_order_id("crypto", "BTCUSDT", ts, "buy", "entry")
    second = client_order_id("crypto", "BTCUSDT", ts, "buy", "entry")
    assert first == second
    assert len(first) <= 36
    assert all(char.isalnum() or char in "_-" for char in first)


def test_reconcile_helper_flags_unexpected_position():
    result = reconcile({"AAA": 0.0}, {"AAA": 2.0})
    assert not result.ok
    assert result.adopted == ["AAA"]


def test_fees_make_the_trade_worse(tmp_path):
    start = datetime(2024, 8, 5, 12, tzinfo=timezone.utc)
    bars = make_bars("AAA", start, [(100, 110, 99, 108, 1), (100, 105, 80, 82, 1)])
    signal = Signal("AAA", bars[0].ts, "buy", "custo", "scripted", stop_price=90)

    def run(fee: float):
        inst = sample_instrument(fee_per_unit_side=fee)
        engine = build(tmp_path / str(fee), inst, Scripted([[signal], []]))
        for bar in bars:
            engine.process_bar(bar)
        return engine.trades[0].pnl

    assert run(0) > run(0.5)
