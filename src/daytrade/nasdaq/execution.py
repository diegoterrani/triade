"""Execução do NASDAQ na IC Markets via MT5.

cTrader também atende a IC Markets. MT5 foi a escolha porque o agente da B3 já
depende do mesmo terminal e o processo daqui usa outro login, outro magic e
outro caminho de terminal. Os dois não compartilham conexão.
"""

from __future__ import annotations

import json

from daytrade.common.app import trip_flatten_flag
from daytrade.common.broker_paper import PaperBroker
from daytrade.common.config import prepare_for_mode, require_env, resolve_path
from daytrade.common.errors import SafetyError
from daytrade.common.feeds import ReplayFeed, load_bars_csv
from daytrade.common.livegate import assert_live_allowed
from daytrade.common.logging_setup import setup_logging
from daytrade.common.mt5_broker import MT5Broker, mt5_connection_kwargs
from daytrade.common.mt5_feed import MT5BarFeed
from daytrade.common.runner import run_loop
from daytrade.common.symbols import IdentityRouter
from daytrade.common.wiring import (
    instruments_from_config,
    journal_for,
    make_engine,
    make_kill,
    paper_broker,
    state_dir,
)
from daytrade.nasdaq.analysis import build_strategies


class SuffixRouter(IdentityRouter):
    def __init__(self, suffix: str = "") -> None:
        self.suffix = suffix

    def venue(self, internal: str, ts) -> str:
        return f"{internal}{self.suffix}"

    def internal(self, venue_symbol: str) -> str:
        if self.suffix and venue_symbol.endswith(self.suffix):
            return venue_symbol[: -len(self.suffix)]
        return venue_symbol


def _router(cfg: dict) -> SuffixRouter:
    return SuffixRouter(str(cfg.get("symbol_suffix") or ""))


def build_broker(cfg: dict, mode: str):
    venue = cfg.get("paper_venue", "simulate")
    if mode == "backtest" or (mode == "paper" and venue == "simulate"):
        return paper_broker(cfg)
    mt5_cfg = cfg["mt5"]
    if mode == "paper" and venue != "demo":
        raise SafetyError("paper_venue do NASDAQ é simulate ou demo")
    if mode == "paper" and not mt5_cfg.get("demo", False):
        raise SafetyError("paper demo exige mt5.demo: true")
    if mode == "live":
        assert_live_allowed(cfg["agent"], bool(cfg.get("live_enabled", False)))
        if mt5_cfg.get("demo", False):
            raise SafetyError("modo live recusado: mt5.demo está true")
    broker = MT5Broker(
        terminal_path=str(mt5_cfg.get("terminal_path") or ""),
        login=require_env(mt5_cfg["login_env"]),
        password=require_env(mt5_cfg["password_env"]),
        server=require_env(mt5_cfg["server_env"]),
        magic=int(mt5_cfg["magic"]),
        instruments=instruments_from_config(cfg),
        router=_router(cfg),
        deviation=int(mt5_cfg.get("deviation", 30)),
        demo=bool(mt5_cfg.get("demo", False)),
        adopt_terminal_spec=bool(cfg.get("adopt_terminal_spec")),
        **mt5_connection_kwargs(mt5_cfg),
    )
    broker.connect()
    return broker


def _resolve_factory(cfg):
    router = _router(cfg)

    def resolve(symbol: str, ts):
        return router.venue(symbol, ts)

    return resolve


def run_realtime(cfg: dict, mode: str, max_bars: int | None, data_path: str | None) -> int:
    if mode == "live":
        assert_live_allowed(cfg["agent"], bool(cfg.get("live_enabled", False)))
        cfg = prepare_for_mode(cfg, mode)
    directory = state_dir(cfg)
    logger = setup_logging(cfg["agent"], directory / "logs" / f"{mode}.jsonl")
    broker = build_broker(cfg, mode)
    equity = float(cfg["risk"]["equity"]) if isinstance(broker, PaperBroker) else float(broker.equity())
    engine = make_engine(
        cfg,
        broker=broker,
        strategies=build_strategies(cfg),
        equity=equity,
        journal=journal_for(cfg, mode),
        resolve_contract=_resolve_factory(cfg),
        kill=make_kill(cfg, enabled=True),
        logger=logger,
        mode=mode,
    )
    _restore(engine)
    if isinstance(broker, PaperBroker):
        path = resolve_path(data_path or cfg["feed"]["path"])
        feed = ReplayFeed(load_bars_csv(path), max_bars=max_bars)
    else:
        feed = MT5BarFeed(
            broker,
            _router(cfg),
            [spec["symbol"] for spec in cfg["symbols"]],
            cfg["feed"]["timeframe"],
            time_offset_hours=float(cfg["mt5"].get("time_offset_hours", 0)),
            max_bars=max_bars,
        )
        engine.reconcile_and_adopt()
    run_loop(feed, engine)
    if hasattr(broker, "shutdown"):
        broker.shutdown()
    return 0


def flatten(cfg: dict, _args=None) -> int:
    flag = trip_flatten_flag(cfg)
    print(f"kill switch gravado em {flag}.")
    venue = cfg.get("paper_venue", "simulate")
    if venue == "simulate" and not cfg.get("live_enabled"):
        print("paper simulado não envia ordem.")
        return 0
    try:
        mode = "live" if cfg.get("live_enabled") and not cfg["mt5"].get("demo", False) else "paper"
        broker = build_broker(cfg, mode)
        print(f"cancelamento enviado ({broker.cancel_all()}). Confira o terminal da IC Markets.")
        broker.shutdown()
    except SafetyError as exc:
        print(f"flag gravado, sem falar com o terminal: {exc}")
    return 0


def _restore(engine) -> None:
    path = engine.persist_path
    if path is None or not path.exists():
        return
    engine.restore_state(json.loads(path.read_text(encoding="utf-8")))
    engine.journal.write("restore", arquivo=str(path))
