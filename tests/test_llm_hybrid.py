"""Validação do analista, separação das fontes e tamanho do perfil micro_live."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from daytrade.common.broker_paper import PaperBroker
from daytrade.common.config import (
    apply_micro_live,
    instrument_from_dict,
    load_config,
    prepare_for_mode,
    risk_limits_from_config,
)
from daytrade.common.errors import SafetyError
from daytrade.common.execution import ExecutionEngine
from daytrade.common.journal import Journal
from daytrade.common.llm_context import build_context
from daytrade.common.llm_control import enqueue, set_param, write_control
from daytrade.common.llm_orders import signal_from_order, validate_order
from daytrade.common.models import Signal
from daytrade.common.config import project_root
from daytrade.common.risk import RiskLimits, RiskManager
from daytrade.common.specs import read_terminal_spec
from daytrade.llm.__main__ import main
from tests.conftest import make_bars, sample_instrument


def _llm_cfg(**overrides) -> dict:
    cfg = {
        "agent": "b3",
        "timezone": "America/Sao_Paulo",
        "symbols": [{"symbol": "WIN"}, {"symbol": "WDO"}],
        "llm": {
            "enabled": True,
            "min_holding_minutes": 30,
            "max_holding_minutes": 240,
            "max_qty": {"WIN": 1, "WDO": 1},
            "parameters": {"atr_mult": {"type": "float", "min": 1.0, "max": 2.5}},
        },
    }
    cfg.update(overrides)
    return cfg


def _order(**overrides) -> dict:
    payload = {
        "idempotency_key": "llm-win-0001",
        "symbol": "WIN",
        "side": "buy",
        "qty": 1,
        "entry_type": "market",
        "stop": 127000,
        "take_profit": 129000,
        "max_holding_minutes": 120,
        "rationale": "preço segurou acima da VWAP",
    }
    payload.update(overrides)
    return payload


class Plan:
    def __init__(self, steps):
        self.steps = list(steps)
        self.seen = []

    def reset(self) -> None:
        return None

    def describe(self) -> dict:
        return {"name": "plan"}

    def on_bar(self, bar, position):
        self.seen.append(None if position is None else position.source)
        if not self.steps:
            return []
        return self.steps.pop(0)


def _engine(tmp_path, strategy, instrument=None, limits=None):
    instrument = instrument or sample_instrument(symbol="AAA", max_qty=5)
    broker = PaperBroker({instrument.symbol: instrument}, 10_000)
    risk = RiskManager(limits or RiskLimits(0.01, 5, 0.05, 0.2), equity=10_000)
    directory = tmp_path / "state"
    return ExecutionEngine(
        agent="t",
        broker=broker,
        risk=risk,
        instruments={instrument.symbol: instrument},
        strategies={instrument.symbol: strategy},
        journal=Journal(directory / "journal" / "paper.jsonl"),
        risk_tz=timezone.utc,
        llm_dir=directory / "llm",
        param_bounds={"atr_mult": {"type": "float", "min": 1, "max": 3}},
    )


def test_schema_rejects_incomplete_and_out_of_bounds_orders():
    cfg = _llm_cfg()
    with pytest.raises(SafetyError, match="stop"):
        validate_order({key: value for key, value in _order().items() if key != "stop"}, cfg)
    with pytest.raises(SafetyError, match="não permitido"):
        validate_order({**_order(), "leverage": 10}, cfg)
    with pytest.raises(SafetyError, match="teto do analista"):
        validate_order(_order(qty=2), cfg)
    with pytest.raises(SafetyError, match="30–240"):
        validate_order(_order(max_holding_minutes=10), cfg)
    with pytest.raises(SafetyError, match="buy ou sell"):
        validate_order(_order(side="long"), cfg)
    with pytest.raises(SafetyError, match="8 a 36"):
        validate_order(_order(idempotency_key="curta"), cfg)
    accepted = validate_order({key: value for key, value in _order().items() if key != "max_holding_minutes"}, cfg)
    assert accepted["max_holding_minutes"] == 240


def test_set_param_stays_inside_the_yaml_and_duplicate_key_does_not_requeue(tmp_path):
    cfg = _llm_cfg()
    with pytest.raises(SafetyError, match="fora da faixa"):
        set_param(cfg, tmp_path, "atr_mult", "9")
    with pytest.raises(SafetyError, match="não pode ser alterado"):
        set_param(cfg, tmp_path, "ema_fast", "5")
    control = set_param(cfg, tmp_path, "atr_mult", "1.8")
    assert control["params"]["atr_mult"] == 1.8
    first = enqueue(tmp_path, validate_order(_order(), cfg))
    second = enqueue(tmp_path, validate_order(_order(), cfg))
    assert second["idempotency_key"] == first["idempotency_key"]
    assert second["status"] == "na_fila"
    assert len(list((tmp_path / "llm" / "inbox").glob("*.json"))) == 1
    journal = (tmp_path / "journal" / "llm.jsonl").read_text(encoding="utf-8")
    assert journal.count('"action": "submit"') == 1
    assert '"source": "llm"' in journal


def test_sources_do_not_net_and_python_cannot_flatten_the_analyst(tmp_path):
    start = datetime(2026, 11, 17, 14, tzinfo=timezone.utc)
    bars = make_bars("AAA", start, [(100, 110, 99, 108, 10), (100, 110, 99, 108, 10), (108, 112, 107, 111, 10)])
    plan = Plan([[], [], [Signal("AAA", bars[2].ts, "buy", "rompimento", "plan", stop_price=90)]])
    engine = _engine(tmp_path, plan)
    order = validate_order(
        _order(symbol="AAA", idempotency_key="llm-aaa-0001", stop=90, take_profit=130, qty=1),
        _llm_cfg(symbols=[{"symbol": "AAA"}]),
    )
    enqueue(tmp_path / "state", order)
    engine.process_bar(bars[0])
    engine.process_bar(bars[1])
    assert engine.positions["AAA"].source == "llm"
    engine.process_bar(bars[2])
    assert engine.positions["AAA"].source == "llm"
    assert plan.seen[2] is None
    text = engine.journal.path.read_text(encoding="utf-8")
    assert "símbolo ocupado pela fonte llm" in text
    assert '"source": "llm"' in text

    start2 = datetime(2026, 11, 18, 14, tzinfo=timezone.utc)
    bars2 = make_bars("AAA", start2, [(100, 110, 99, 108, 10), (100, 110, 99, 108, 10), (108, 112, 107, 111, 10)])
    buy = Signal("AAA", bars2[0].ts, "buy", "python", "plan", stop_price=90)
    engine2 = _engine(tmp_path / "py", Plan([[buy], [], []]))
    engine2.process_bar(bars2[0])
    engine2.process_bar(bars2[1])
    assert engine2.positions["AAA"].source == "python"
    enqueue(
        tmp_path / "py" / "state",
        validate_order(
            _order(symbol="AAA", idempotency_key="llm-aaa-0002", stop=90, take_profit=130),
            _llm_cfg(symbols=[{"symbol": "AAA"}]),
        ),
    )
    engine2.process_bar(bars2[2])
    assert engine2.positions["AAA"].source == "python"
    assert "símbolo ocupado pela fonte python" in engine2.journal.path.read_text(encoding="utf-8")


def test_disable_blocks_new_entries_and_the_stop_still_runs(tmp_path):
    start = datetime(2026, 11, 17, 14, tzinfo=timezone.utc)
    bars = make_bars(
        "AAA",
        start,
        [
            (100, 110, 99, 108, 10),
            (100, 110, 99, 108, 10),
            (90, 91, 80, 82, 10),
        ],
    )
    later = Signal("AAA", bars[2].ts, "buy", "depois do desligamento", "plan", stop_price=70)
    engine = _engine(tmp_path, Plan([[Signal("AAA", bars[0].ts, "buy", "abertura", "plan", stop_price=90)], [], [later]]))
    engine.process_bar(bars[0])
    engine.process_bar(bars[1])
    write_control(tmp_path / "state", {"enabled": False})
    engine.process_bar(bars[2])
    assert engine.trades[0].exit_reason == "stop"
    assert engine.trades[0].source == "python"
    assert "AAA" not in engine.positions
    assert "agente desligado pelo analista" in engine.journal.path.read_text(encoding="utf-8")


def test_llm_position_exits_on_max_holding_time(tmp_path):
    start = datetime(2026, 11, 17, 14, tzinfo=timezone.utc)
    bars = make_bars("AAA", start, [(100, 110, 99, 108, 10), (100, 110, 99, 108, 10), (108, 112, 107, 111, 10)], step_min=30)
    engine = _engine(tmp_path, Plan([[], [], []]))
    order = validate_order(
        _order(symbol="AAA", idempotency_key="llm-hold-001", stop=90, take_profit=140, max_holding_minutes=30, qty=1),
        _llm_cfg(symbols=[{"symbol": "AAA"}]),
    )
    enqueue(tmp_path / "state", order)
    engine.process_bar(bars[0])
    engine.process_bar(bars[1])
    assert "AAA" in engine.positions
    engine.process_bar(bars[2])
    assert engine.trades[0].exit_reason == "tempo máximo da mão"
    assert engine.trades[0].source == "llm"


def test_context_lists_ptax_and_cli_submit_is_idempotent(tmp_path, capsys):
    now = datetime(2026, 11, 17, 9, 30, tzinfo=ZoneInfo("America/Sao_Paulo"))
    snapshot = build_context(
        load_config("configs/b3.yaml"),
        now=now,
        bars=[],
        state={"realized_pnl_today": -10, "pnl_by_source": {"python": -10, "llm": 0}},
        control={},
        enabled=True,
        kill_reason=None,
    )
    assert any("PTAX" in item["label"] for item in snapshot["upcoming_events"])
    assert snapshot["pnl_today"]["by_source"]["python"] == -10

    cfg_path = tmp_path / "b3.yaml"
    cfg = _llm_cfg()
    cfg["paths"] = {"state_dir": str(tmp_path / "cli-state")}
    cfg_path.write_text(__import__("yaml").safe_dump(cfg, allow_unicode=True), encoding="utf-8")
    order_path = tmp_path / "order.json"
    order_path.write_text(json.dumps(_order()), encoding="utf-8")
    assert main(["b3", "--config", str(cfg_path), "submit", "--file", str(order_path)]) == 0
    assert main(["b3", "--config", str(cfg_path), "submit", "--file", str(order_path)]) == 0
    out = capsys.readouterr().out
    assert out.count("na_fila") == 2
    assert len(list((tmp_path / "cli-state" / "llm" / "inbox").glob("*.json"))) == 1
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"symbol": "WIN"}), encoding="utf-8")
    assert main(["b3", "--config", str(cfg_path), "submit", "--file", str(bad)]) == 2
    assert "erro:" in capsys.readouterr().out


def test_micro_live_sizes_one_b3_contract_and_min_notional():
    b3 = load_config("configs/b3.yaml")
    research = risk_limits_from_config(b3)
    assert research.max_trades_per_source["python"] == 6
    assert research.source_daily_loss_pct is None
    assert prepare_for_mode(b3, "paper") is b3
    with pytest.raises(SafetyError, match="micro_live"):
        prepare_for_mode({"risk": b3["risk"]}, "live")

    live = apply_micro_live(b3)
    win = instrument_from_dict("WIN", next(item for item in live["symbols"] if item["symbol"] == "WIN"), "BRL")
    assert win.max_qty == 1
    risk = RiskManager(risk_limits_from_config(live), equity=5000)
    now = datetime(2026, 11, 17, 15, tzinfo=timezone.utc)
    tight = Signal("WIN", now, "buy", "micro", "llm_analyst", stop_price=99750, source="llm", requested_qty=1)
    wide = Signal("WIN", now, "buy", "micro", "llm_analyst", stop_price=99000, source="llm", requested_qty=1)
    assert risk.approve_entry(tight, 5000, win, 100000).qty == 1
    assert risk.approve_entry(wide, 5000, win, 100000).qty == 0

    crypto = apply_micro_live(load_config("configs/crypto.yaml"))
    btc = instrument_from_dict("BTCUSDT", next(item for item in crypto["symbols"] if item["symbol"] == "BTCUSDT"), "USDT")
    crypto_risk = RiskManager(risk_limits_from_config(crypto), equity=1000)
    assert crypto_risk.limits.sizing_mode == "min_notional"
    assert crypto["leverage"] == 2
    small_stop = Signal("BTCUSDT", now, "buy", "micro", "llm_analyst", stop_price=99900, source="llm", requested_qty=0.01)
    huge_stop = Signal("BTCUSDT", now, "buy", "micro", "llm_analyst", stop_price=50000, source="llm", requested_qty=0.01)
    assert crypto_risk.approve_entry(small_stop, 1000, btc, 100000).qty == pytest.approx(0.001)
    assert crypto_risk.approve_entry(huge_stop, 1000, btc, 100000).qty == 0
    with pytest.raises(SafetyError, match="1x ou 2x"):
        apply_micro_live({**load_config("configs/crypto.yaml"), "micro_live": {**crypto["micro_live"], "leverage": 3}})


def test_terminal_spec_is_required_and_source_loss_does_not_halt_the_other_source():
    with pytest.raises(SafetyError, match="lote mínimo"):
        read_terminal_spec("USTEC", volume_min=None, volume_step=0.1, tick_size=0.1, tick_value=0.1)
    spec = read_terminal_spec("USTEC", volume_min=0.1, volume_step=0.1, tick_size=0.1, tick_value=0.1)
    assert spec["point_value"] == pytest.approx(1.0)
    assert spec["min_qty"] == 0.1

    cfg = apply_micro_live(load_config("configs/b3.yaml"))
    risk = RiskManager(risk_limits_from_config(cfg), equity=5000)
    risk.start_day(datetime(2026, 11, 17, tzinfo=timezone.utc).date(), 5000)
    risk.note_realized(-40, "llm")
    assert "llm" in risk.state.source_halted
    now = datetime(2026, 11, 17, 15, tzinfo=timezone.utc)
    win = instrument_from_dict("WIN", next(item for item in cfg["symbols"] if item["symbol"] == "WIN"), "BRL")
    python_signal = Signal("WIN", now, "buy", "python", "orb", stop_price=99750, source="python")
    llm_signal = Signal("WIN", now, "buy", "llm", "llm_analyst", stop_price=99750, source="llm", requested_qty=1)
    assert risk.approve_entry(python_signal, 5000, win, 100000).approved
    assert risk.approve_entry(llm_signal, 5000, win, 100000).reason == "limite diário da fonte"


def test_example_order_file_validates_against_b3():
    payload = json.loads((project_root() / "examples" / "llm-order-win.json").read_text(encoding="utf-8"))
    order = validate_order(payload, load_config("configs/b3.yaml"))
    signal = signal_from_order(order, datetime(2026, 11, 17, 15, tzinfo=timezone.utc))
    assert signal.source == "llm"
    assert signal.client_order_id == "llm-win-20261117-001"
    assert signal.max_hold_minutes == 120
    assert signal.symbol == "WIN"
