"""Kill switch global ou de um agente. Só grava arquivo. Quem está no ar é que zera.

Não conecta na corretora. Para zerar com o processo caído, use o flatten daquele agente.
"""

from __future__ import annotations

import argparse

from daytrade.common.config import project_root
from daytrade.common.killswitch import KillSwitch

AGENTS = ("b3", "crypto", "nasdaq")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="daytrade-kill",
        description="Trava um agente ou todos. O processo correspondente cancela e zera.",
    )
    parser.add_argument("agent", nargs="?", choices=AGENTS)
    parser.add_argument("--all", action="store_true", help="Flag global, visto por todos os agentes")
    parser.add_argument("--clear", action="store_true", help="Remove o flag. Não religa um processo já encerrado.")
    parser.add_argument("--reason", default="kill switch acionado manualmente")
    args = parser.parse_args(argv)
    if not args.all and args.agent is None:
        parser.error("informe o agente ou --all")
    root = project_root() / "var"
    if args.all:
        switch = KillSwitch("all", root)
        if args.clear:
            removed = switch.clear(global_=True)
            for name in AGENTS:
                removed = KillSwitch(name, root).clear() or removed
            print("flags globais e dos agentes removidos" if removed else "não havia flag")
            return 0
        path = switch.trip(args.reason, global_=True)
        print(f"KILL_ALL gravado em {path}. Cada processo no ar vai zerar e sair.")
        return 0
    switch = KillSwitch(args.agent, root)
    if args.clear:
        print("flag removido" if switch.clear() else "esse agente não estava travado")
        return 0
    path = switch.trip(args.reason)
    print(f"flag de {args.agent} gravado em {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
