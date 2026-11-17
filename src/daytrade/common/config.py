"""Caminhos e leitura de YAML. Segredos continuam no ambiente, não no arquivo."""

from __future__ import annotations

import copy
import os
from pathlib import Path

import yaml
from dotenv import load_dotenv

from daytrade.common.errors import SafetyError
from daytrade.common.models import Instrument
from daytrade.common.risk import RiskLimits


def project_root() -> Path:
    start = Path(__file__).resolve()
    for candidate in start.parents:
        if (candidate / "pyproject.toml").exists():
            return candidate
    return Path.cwd()


def resolve_path(value: str | Path) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    return project_root() / path


def load_config(path: str | Path) -> dict:
    load_dotenv(project_root() / ".env")
    file_path = Path(path)
    if not file_path.is_absolute():
        file_path = project_root() / file_path
    if not file_path.exists():
        raise SafetyError(f"config não encontrado: {file_path}")
    with file_path.open(encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    if not isinstance(data, dict):
        raise SafetyError(f"config inválido: {file_path}")
    data["_config_path"] = str(file_path)
    return data


def require_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise SafetyError(f"variável de ambiente {name} não definida")
    return value


def env_or_blank(name: str) -> str:
    return os.environ.get(name, "").strip()


def instrument_from_dict(symbol: str, spec: dict, currency: str) -> Instrument:
    return Instrument(
        symbol=symbol,
        root=str(spec.get("root", symbol)),
        tick_size=float(spec["tick_size"]),
        point_value=float(spec["point_value"]),
        lot_step=float(spec["lot_step"]),
        min_qty=float(spec["min_qty"]),
        currency=currency,
        fee_per_unit_side=float(spec.get("fee_per_unit_side", 0.0)),
        fee_rate_side=float(spec.get("fee_rate_side", 0.0)),
        slippage_ticks=float(spec.get("slippage_ticks", 0.0)),
        max_qty=float(spec["max_qty"]),
        min_notional=float(spec.get("min_notional", 0.0)),
    )


def risk_limits_from_config(cfg: dict) -> RiskLimits:
    risk = cfg["risk"]
    llm = cfg.get("llm") or {}
    per_source = llm.get("max_trades_per_source") or None
    if per_source is not None:
        per_source = {str(key): int(value) for key, value in per_source.items()}
    source_loss = llm.get("source_daily_loss_pct")
    return RiskLimits(
        risk_per_trade_pct=float(risk["risk_per_trade_pct"]),
        max_trades_per_day=int(risk["max_trades_per_day"]),
        daily_loss_limit_pct=float(risk["daily_loss_limit_pct"]),
        max_drawdown_pct=float(risk["max_drawdown_pct"]),
        sticky_drawdown_halt=bool(risk.get("sticky_drawdown_halt", True)),
        max_trades_per_source=per_source,
        source_daily_loss_pct=None if source_loss is None else float(source_loss),
        sizing_mode=str(llm.get("sizing_mode") or risk.get("sizing_mode") or "risk"),
    )


def assert_micro_leverage(leverage: int) -> int:
    if leverage < 1 or leverage > 2:
        raise SafetyError("micro_live só aceita alavancagem de 1x ou 2x, margem isolada")
    return leverage


def apply_micro_live(cfg: dict) -> dict:
    """Recorta o config para a conta real pequena. Não mexe na trava do live."""
    if "micro_live" not in cfg:
        raise SafetyError("modo live exige o perfil micro_live no YAML deste agente")
    updated = copy.deepcopy(cfg)
    micro = updated["micro_live"]
    risk = updated["risk"]
    for key in (
        "equity",
        "risk_per_trade_pct",
        "max_trades_per_day",
        "daily_loss_limit_pct",
        "max_drawdown_pct",
    ):
        if key in micro:
            risk[key] = micro[key]
    llm = updated.setdefault("llm", {})
    if "max_trades_per_source" in micro:
        llm["max_trades_per_source"] = micro["max_trades_per_source"]
    if "source_daily_loss_pct" in micro:
        llm["source_daily_loss_pct"] = micro["source_daily_loss_pct"]
    if "sizing_mode" in micro:
        llm["sizing_mode"] = micro["sizing_mode"]
    for spec in updated.get("symbols", []):
        cap = (micro.get("max_qty") or {}).get(spec["symbol"])
        if cap is not None:
            spec["max_qty"] = cap
            llm.setdefault("max_qty", {})[spec["symbol"]] = cap
    if "min_notional" in micro:
        for spec in updated.get("symbols", []):
            spec["min_notional"] = micro["min_notional"]
    if micro.get("leverage") is not None:
        updated["leverage"] = assert_micro_leverage(int(micro["leverage"]))
        updated["margin_type"] = str(micro.get("margin_type", "isolated"))
    if "market" in micro:
        updated["market"] = micro["market"]
        if micro["market"] == "spot":
            updated.setdefault("strategy", {})["allow_short"] = False
    updated["adopt_terminal_spec"] = bool(micro.get("adopt_terminal_spec", False))
    updated["active_profile"] = "micro_live"
    return updated


def prepare_for_mode(cfg: dict, mode: str) -> dict:
    if mode != "live":
        return cfg
    return apply_micro_live(cfg)
