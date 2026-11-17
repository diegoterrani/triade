"""CLI do analista. Um agente por invocação. Não envia ordem à corretora.

    python -m daytrade.llm b3 submit --file order.json
    python -m daytrade.llm b3 status
    python -m daytrade.llm b3 context
    python -m daytrade.llm b3 set-param atr_mult 1.8
    python -m daytrade.llm b3 enable
    python -m daytrade.llm b3 disable
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from daytrade.common.config import load_config, resolve_path
from daytrade.common.errors import SafetyError
from daytrade.common.feeds import load_bars_csv
from daytrade.common.killswitch import KillSwitch
from daytrade.common.llm_context import build_context
from daytrade.common.llm_control import (
    agent_enabled,
    enqueue,
    read_control,
    set_enabled,
    set_param,
)
from daytrade.common.llm_orders import validate_order
from daytrade.common.wiring import state_dir

AGENTS = ("b3", "crypto", "nasdaq")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="daytrade-llm",
        description="Pedidos do analista. O risco do agente continua obrigatório.",
    )
    parser.add_argument("agent", choices=AGENTS)
    parser.add_argument("--config", default=None, help="YAML deste agente")
    sub = parser.add_subparsers(dest="cmd", required=True)
    submit = sub.add_parser("submit", help="Enfileira uma ordem. Não fala com a corretora.")
    submit.add_argument("--file", required=True)
    sub.add_parser("status")
    sub.add_parser("context")
    param = sub.add_parser("set-param")
    param.add_argument("name")
    param.add_argument("value")
    sub.add_parser("enable")
    sub.add_parser("disable")
    args = parser.parse_args(argv)
    try:
        cfg = load_config(args.config or f"configs/{args.agent}.yaml")
        if cfg.get("agent") != args.agent:
            raise SafetyError(f"o config é do agente {cfg.get('agent')}, não de {args.agent}")
        if args.cmd == "submit":
            return _submit(cfg, Path(args.file))
        if args.cmd == "status":
            return _status(cfg)
        if args.cmd == "context":
            return _context(cfg)
        if args.cmd == "set-param":
            control = set_param(cfg, state_dir(cfg), args.name, args.value)
            print(json.dumps({"ok": True, "params": control.get("params")}, ensure_ascii=False))
            return 0
        control = set_enabled(cfg, state_dir(cfg), args.cmd == "enable")
        print(json.dumps({"ok": True, "enabled": control["enabled"]}, ensure_ascii=False))
        return 0
    except (SafetyError, ValueError, OSError, json.JSONDecodeError) as exc:
        print(f"erro: {exc}")
        return 2


def _submit(cfg: dict, path: Path) -> int:
    payload = json.loads(path.read_text(encoding="utf-8"))
    order = validate_order(payload, cfg)
    record = enqueue(state_dir(cfg), order)
    print(json.dumps(record, ensure_ascii=False))
    if record.get("status") == "recusada":
        return 2
    return 0


def _status(cfg: dict) -> int:
    directory = state_dir(cfg)
    kill = KillSwitch(cfg["agent"], directory.parent)
    state_file = _latest_state(directory)
    state = json.loads(state_file.read_text(encoding="utf-8")) if state_file else {}
    print(
        json.dumps(
            {
                "agent": cfg["agent"],
                "enabled": agent_enabled(cfg, directory),
                "live_enabled": bool(cfg.get("live_enabled", False)),
                "profile": cfg.get("active_profile", "research"),
                "kill": kill.tripped(),
                "halted": state.get("halted"),
                "halt_reason": state.get("halt_reason"),
                "trades_today": state.get("trades_today"),
                "pnl_by_source": state.get("pnl_by_source") or {},
                "positions": [
                    {"symbol": item.get("symbol"), "qty": item.get("qty"), "source": item.get("source", "python")}
                    for item in state.get("positions") or []
                ],
            },
            ensure_ascii=False,
        )
    )
    return 0


def _context(cfg: dict) -> int:
    directory = state_dir(cfg)
    bars = _recent_bars(cfg, directory)
    state_file = _latest_state(directory)
    state = json.loads(state_file.read_text(encoding="utf-8")) if state_file else {}
    kill = KillSwitch(cfg["agent"], directory.parent)
    snapshot = build_context(
        cfg,
        now=datetime.now(timezone.utc),
        bars=bars,
        state=state,
        control=read_control(directory),
        enabled=agent_enabled(cfg, directory),
        kill_reason=kill.tripped(),
    )
    print(json.dumps(snapshot, ensure_ascii=False))
    return 0


def _latest_state(directory: Path) -> Path | None:
    files = sorted(directory.glob("*-state.json"))
    return files[-1] if files else None


def _recent_bars(cfg: dict, directory: Path):
    cache = directory / "recent-bars.json"
    if cache.exists():
        raw = json.loads(cache.read_text(encoding="utf-8"))
        from daytrade.common.models import Bar

        bars = []
        for item in raw:
            ts = datetime.fromisoformat(item["ts"])
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            bars.append(
                Bar(
                    symbol=item["symbol"],
                    ts=ts,
                    open=float(item["open"]),
                    high=float(item["high"]),
                    low=float(item["low"]),
                    close=float(item["close"]),
                    volume=float(item["volume"]),
                    timeframe=item.get("timeframe", "5m"),
                )
            )
        return bars
    feed = cfg.get("feed") or {}
    if feed.get("path"):
        wanted = {spec["symbol"] for spec in cfg.get("symbols", [])}
        bars = [bar for bar in load_bars_csv(resolve_path(feed["path"])) if bar.symbol in wanted]
        return bars[-400:]
    return []


if __name__ == "__main__":
    sys.exit(main())
