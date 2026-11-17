"""Montagem do motor. O agente escolhe a corretora; o miolo de risco é o mesmo."""

from __future__ import annotations

import logging
import os
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from daytrade.common.broker_paper import PaperBroker
from daytrade.common.config import instrument_from_dict, resolve_path, risk_limits_from_config
from daytrade.common.execution import ExecutionEngine
from daytrade.common.journal import Journal
from daytrade.common.killswitch import KillSwitch
from daytrade.common.models import Instrument
from daytrade.common.notify import build_notifier
from daytrade.common.risk import RiskManager


def instruments_from_config(cfg: dict) -> dict[str, Instrument]:
    currency = cfg["currency"]
    return {
        spec["symbol"]: instrument_from_dict(spec["symbol"], spec, currency) for spec in cfg["symbols"]
    }


def state_dir(cfg: dict) -> Path:
    return resolve_path(cfg["paths"]["state_dir"])


def make_kill(cfg: dict, *, enabled: bool) -> KillSwitch:
    directory = state_dir(cfg)
    return KillSwitch(cfg["agent"], directory.parent, enabled=enabled)


def make_engine(
    cfg: dict,
    *,
    broker,
    strategies: dict,
    equity: float,
    journal: Journal,
    resolve_contract: Callable[[str, datetime], str],
    kill: KillSwitch | None,
    logger: logging.Logger,
    mode: str,
) -> ExecutionEngine:
    directory = state_dir(cfg)
    limits = risk_limits_from_config(cfg)
    instruments = getattr(broker, "instruments", None) or instruments_from_config(cfg)
    engine = ExecutionEngine(
        agent=cfg["agent"],
        broker=broker,
        risk=RiskManager(limits, equity=equity),
        instruments=instruments,
        strategies=strategies,
        journal=journal,
        risk_tz=ZoneInfo(cfg["timezone"]),
        resolve_contract=resolve_contract,
        kill=kill,
        logger=logger,
        notifier=build_notifier(
            bool(cfg.get("notifications", {}).get("telegram_enabled", False)),
            os.environ,
            logger,
        ),
        emergency_stop_pct=float(cfg.get("emergency_stop_pct", 0.01)),
        persist_path=None if mode == "backtest" else directory / f"{mode}-state.json",
        llm_dir=None if mode == "backtest" else directory / "llm",
        param_bounds=(cfg.get("llm") or {}).get("parameters") or {},
        analyst_enabled=bool((cfg.get("llm") or {}).get("enabled", True)),
        volume_spike_multiple=float((cfg.get("llm") or {}).get("volume_spike_multiple", 2.0)),
    )
    return engine


def paper_broker(cfg: dict) -> PaperBroker:
    equity = float(cfg["risk"]["equity"])
    return PaperBroker(instruments_from_config(cfg), equity)


def journal_for(cfg: dict, mode: str) -> Journal:
    return Journal(state_dir(cfg) / "journal" / f"{mode}.jsonl")
