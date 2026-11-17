"""Estudo do agente de cripto. A amostra pública entra pelo CSV; a rede fica no script de download."""

from __future__ import annotations

from daytrade.common.study_job import run_study
from daytrade.crypto.strategy import build_strategies


def _resolve(symbol: str, _ts) -> str:
    return symbol


def execute(cfg: dict, data_path: str | None = None, artifact_name: str | None = None) -> dict:
    return run_study(
        cfg,
        build_strategies=build_strategies,
        resolve_contract=_resolve,
        data_path=data_path,
        artifact_name=artifact_name,
    )
