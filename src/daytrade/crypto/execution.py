"""Execução do agente de cripto. Simulate não assina ordem. Testnet e live assinam."""

from __future__ import annotations

import json

from daytrade.common.app import trip_flatten_flag
from daytrade.common.broker_paper import PaperBroker
from daytrade.common.config import env_or_blank, resolve_path
from daytrade.common.errors import SafetyError
from daytrade.common.feeds import ReplayFeed, load_bars_csv
from daytrade.common.livegate import assert_live_allowed
from daytrade.common.logging_setup import setup_logging
from daytrade.common.runner import run_loop
from daytrade.common.wiring import (
    instruments_from_config,
    journal_for,
    make_engine,
    make_kill,
    paper_broker,
    state_dir,
)
from daytrade.crypto.binance_api import BinanceBroker, BinancePublicFeed
from daytrade.crypto.strategy import build_strategies


def build_broker(cfg: dict, mode: str):
    venue = cfg.get("paper_venue", "simulate")
    market = cfg.get("market", "usdm")
    if mode == "backtest" or (mode == "paper" and venue == "simulate"):
        return paper_broker(cfg)
    if mode == "paper" and venue != "testnet":
        raise SafetyError("paper_venue do cripto é simulate ou testnet")
    testnet = mode != "live"
    if mode == "live":
        assert_live_allowed(cfg["agent"], bool(cfg.get("live_enabled", False)))
        key = env_or_blank("BINANCE_API_KEY")
        secret = env_or_blank("BINANCE_API_SECRET")
    else:
        key = env_or_blank("BINANCE_TESTNET_API_KEY")
        secret = env_or_blank("BINANCE_TESTNET_API_SECRET")
    broker = BinanceBroker(
        market=market,
        testnet=testnet,
        api_key=key,
        api_secret=secret,
        instruments=instruments_from_config(cfg),
    )
    broker.connect()
    return broker


def _resolve(symbol: str, _ts):
    return symbol


def run_realtime(cfg: dict, mode: str, max_bars: int | None, data_path: str | None) -> int:
    if mode == "live":
        assert_live_allowed(cfg["agent"], bool(cfg.get("live_enabled", False)))
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
        resolve_contract=_resolve,
        kill=make_kill(cfg, enabled=True),
        logger=logger,
        mode=mode,
    )
    _restore(engine)
    feed_kind = cfg.get("feed", {}).get("kind", "replay")
    if isinstance(broker, PaperBroker) and feed_kind == "binance_public":
        feed = BinancePublicFeed(
            [spec["symbol"] for spec in cfg["symbols"]],
            cfg["feed"]["timeframe"],
            market=cfg.get("market", "usdm"),
            max_bars=max_bars,
        )
    elif isinstance(broker, PaperBroker):
        path = resolve_path(data_path or cfg["feed"]["path"])
        feed = ReplayFeed(load_bars_csv(path), max_bars=max_bars)
    else:
        feed = BinancePublicFeed(
            [spec["symbol"] for spec in cfg["symbols"]],
            cfg["feed"]["timeframe"],
            market=cfg.get("market", "usdm"),
            max_bars=max_bars,
            testnet=bool(getattr(broker, "testnet", False)),
        )
        engine.reconcile_and_adopt()
    run_loop(feed, engine)
    return 0


def flatten(cfg: dict, _args=None) -> int:
    flag = trip_flatten_flag(cfg)
    print(f"kill switch gravado em {flag}.")
    venue = cfg.get("paper_venue", "simulate")
    if venue == "simulate" and not cfg.get("live_enabled"):
        print("paper simulado não envia ordem.")
        return 0
    try:
        broker = build_broker(cfg, "live" if cfg.get("live_enabled") else "paper")
        print(f"cancelamento: {broker.cancel_all()} símbolos.")
    except SafetyError as exc:
        print(f"flag gravado, sem falar com a Binance: {exc}")
    return 0


def _restore(engine) -> None:
    path = engine.persist_path
    if path is None or not path.exists():
        return
    engine.restore_state(json.loads(path.read_text(encoding="utf-8")))
    engine.journal.write("restore", arquivo=str(path))
