"""Estudo do NASDAQ. O CSV de amostra é sintético e está marcado como tal no config."""

from __future__ import annotations

from daytrade.common.study_job import run_study
from daytrade.nasdaq.analysis import build_strategies
from daytrade.nasdaq.execution import _resolve_factory


def execute(cfg: dict, data_path: str | None = None, artifact_name: str | None = None) -> dict:
    return run_study(
        cfg,
        build_strategies=build_strategies,
        resolve_contract=_resolve_factory(cfg),
        data_path=data_path,
        artifact_name=artifact_name,
    )
