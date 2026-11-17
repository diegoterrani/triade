"""Despacho dos comandos. Cada processo chama isto com o próprio agente."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

from daytrade.common.config import load_config
from daytrade.common.errors import LiveGateError, SafetyError
from daytrade.common.killswitch import KillSwitch
from daytrade.common.livegate import assert_live_allowed
from daytrade.common.wiring import state_dir


def dispatch(
    agent: str,
    default_config: str,
    argv: list[str] | None,
    parser_factory: Callable,
    commands: dict[str, Callable],
) -> int:
    parser = parser_factory()
    args = parser.parse_args(argv)
    try:
        cfg = load_config(args.config or default_config)
        if cfg.get("agent") != agent:
            raise SafetyError(f"o config {args.config} é do agente {cfg.get('agent')}, não de {agent}")
        return int(commands[args.cmd](cfg, args) or 0)
    except (SafetyError, LiveGateError, ValueError) as exc:
        print(f"erro: {exc}")
        return 2


def show_status(cfg: dict, _args) -> int:
    directory = state_dir(cfg)
    kill = KillSwitch(cfg["agent"], directory.parent)
    print(f"agente: {cfg['agent']}")
    print(f"live_enabled: {bool(cfg.get('live_enabled', False))}")
    print(f"paper_venue: {cfg.get('paper_venue', 'simulate')}")
    reason = kill.tripped()
    print(f"kill switch: {reason or 'livre'}")
    state_files = sorted(directory.glob("*-state.json"))
    if not state_files:
        print("estado: ainda sem arquivo (nenhum paper/live nesta máquina)")
        return 0
    for path in state_files:
        payload = json.loads(path.read_text(encoding="utf-8"))
        print(
            f"{path.name}: halt={payload.get('halted')} motivo={payload.get('halt_reason')} "
            f"trades_hoje={payload.get('trades_today')} posições={len(payload.get('positions') or [])}"
        )
    return 0


def reset_halt(cfg: dict, _args) -> int:
    directory = state_dir(cfg)
    files = sorted(directory.glob("*-state.json"))
    if not files:
        print("não há estado para liberar")
        return 0
    for path in files:
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["halted"] = False
        payload["sticky_halt"] = False
        payload["halt_reason"] = None
        payload["block_entries"] = False
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"halt limpo em {path}. O kill switch, se existir, continua valendo.")
    return 0


def trip_flatten_flag(cfg: dict) -> Path:
    directory = state_dir(cfg)
    kill = KillSwitch(cfg["agent"], directory.parent)
    return kill.trip(f"comando flatten do agente {cfg['agent']}")
