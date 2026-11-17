"""Um estudo: dados, três janelas, relatório. O agente entrega a estratégia e o símbolo."""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from pathlib import Path
from zoneinfo import ZoneInfo

from daytrade.common.backtest import render_report, run_walk_forward
from daytrade.common.broker_paper import PaperBroker
from daytrade.common.config import resolve_path
from daytrade.common.feeds import load_bars_csv
from daytrade.common.logging_setup import log_event, setup_logging
from daytrade.common.wiring import instruments_from_config, journal_for, make_engine, make_kill, state_dir


def run_study(
    cfg: dict,
    *,
    build_strategies: Callable[[dict], dict],
    resolve_contract: Callable,
    data_path: str | None = None,
    artifact_name: str | None = None,
) -> dict:
    instruments = instruments_from_config(cfg)
    path = Path(data_path) if data_path else resolve_path(cfg["feed"]["path"])
    wanted = set(instruments)
    bars = [bar for bar in load_bars_csv(path) if bar.symbol in wanted]
    if not bars:
        raise ValueError(f"nenhuma barra em {path} para {sorted(wanted)}")
    journal_path = state_dir(cfg) / "journal" / "backtest.jsonl"
    if journal_path.exists():
        journal_path.unlink()
    equity = float(cfg["risk"]["equity"])
    directory = state_dir(cfg)
    logger = setup_logging(cfg["agent"], directory / "logs" / "backtest.jsonl")
    journal = journal_for(cfg, "backtest")
    log_event(logger, logging.INFO, "estudo iniciado", barras=len(bars), arquivo=str(path))

    def factory():
        return make_engine(
            cfg,
            broker=PaperBroker(instruments, equity),
            strategies=build_strategies(cfg),
            equity=equity,
            journal=journal,
            resolve_contract=resolve_contract,
            kill=make_kill(cfg, enabled=False),
            logger=logger,
            mode="backtest",
        )

    strategy = next(iter(build_strategies(cfg).values()))
    report = run_walk_forward(
        factory,
        bars,
        tz=ZoneInfo(cfg["timezone"]),
        oos_fraction=float(cfg.get("backtest", {}).get("oos_fraction", 0.3)),
        sharpe_periods=int(cfg.get("sharpe_periods", 252)),
        currency=cfg["currency"],
        initial_equity=equity,
    )
    report["agent"] = cfg["agent"]
    report["strategy"] = strategy.describe()
    report["data"] = {"path": str(path), "source": cfg.get("feed", {}).get("source", "amostra local")}
    report["disclaimer"] = (
        "Resultado histórico de um ponto de partida configurável. Não é recomendação nem promessa de lucro."
    )
    name = artifact_name or cfg["agent"]
    artifact_dir = resolve_path(cfg["paths"]["artifact_dir"])
    artifact_dir.mkdir(parents=True, exist_ok=True)
    (artifact_dir / f"{name}.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    costs = ", ".join(
        f"{symbol}: fee {inst.fee_per_unit_side:g}/lado + {inst.fee_rate_side:.4%} notional, "
        f"slippage {inst.slippage_ticks:g} ticks"
        for symbol, inst in instruments.items()
    )
    markdown = render_report(cfg["agent"], strategy.describe(), costs, report)
    (artifact_dir / f"{name}.md").write_text(markdown, encoding="utf-8")
    log_event(
        logger,
        logging.INFO,
        "estudo concluído",
        trades=report["amostra_cheia"]["trades"],
        pnl=report["amostra_cheia"]["net_pnl"],
    )
    print(markdown)
    print(f"relatório: {artifact_dir / f'{name}.json'}")
    return report
