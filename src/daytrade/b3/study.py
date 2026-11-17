"""Estudo do agente B3 em CSV. Os custos são os do config, não uma tabela escondida."""

from __future__ import annotations

from daytrade.b3.analysis import build_strategies
from daytrade.b3.execution import _resolve_factory
from daytrade.common.study_job import run_study


def execute(cfg: dict, data_path: str | None = None, artifact_name: str | None = None) -> dict:
    return run_study(
        cfg,
        build_strategies=build_strategies,
        resolve_contract=_resolve_factory(cfg),
        data_path=data_path,
        artifact_name=artifact_name,
    )
