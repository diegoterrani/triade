"""Caminhos e leitura de YAML. Segredos continuam no ambiente, não no arquivo."""

from __future__ import annotations

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
    )


def risk_limits_from_config(cfg: dict) -> RiskLimits:
    risk = cfg["risk"]
    return RiskLimits(
        risk_per_trade_pct=float(risk["risk_per_trade_pct"]),
        max_trades_per_day=int(risk["max_trades_per_day"]),
        daily_loss_limit_pct=float(risk["daily_loss_limit_pct"]),
        max_drawdown_pct=float(risk["max_drawdown_pct"]),
        sticky_drawdown_halt=bool(risk.get("sticky_drawdown_halt", True)),
    )
