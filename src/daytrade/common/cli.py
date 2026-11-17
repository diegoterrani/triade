"""Argumentos iguais nos três agentes. O processo de um não sobe o outro."""

from __future__ import annotations

import argparse


def build_parser(prog: str, description: str, default_config: str) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog=prog, description=description)
    parser.add_argument("--config", default=default_config, help="YAML deste agente")
    sub = parser.add_subparsers(dest="cmd", required=True)

    def command(name: str, help_text: str) -> argparse.ArgumentParser:
        # SUPPRESS keeps a --config placed before the subcomando.
        child = sub.add_parser(name, help=help_text)
        child.add_argument("--config", default=argparse.SUPPRESS, help="YAML deste agente")
        return child

    backtest = command("backtest", "Estudo em dados históricos")
    backtest.add_argument("--data", default=None, help="CSV alternativo")

    paper = command("paper", "Ordens simuladas. É o padrão seguro.")
    paper.add_argument("--max-bars", type=int, default=None, help="Encerra depois de N barras")
    paper.add_argument("--data", default=None, help="CSV de replay")

    command("live", "Conta real. Exige live_enabled e DAYTRADE_LIVE_CONFIRM.")
    command("flatten", "Grava o kill switch e tenta zerar na corretora")
    command("reset-halt", "Libera o halt de drawdown depois de revisão manual")
    command("status", "Mostra kill switch, halt e último estado")
    return parser
