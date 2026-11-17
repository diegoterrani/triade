"""Agente de cripto. Processo próprio. Não importa B3 nem NASDAQ."""

from __future__ import annotations

from daytrade.common.app import dispatch, reset_halt, show_status
from daytrade.common.cli import build_parser
from daytrade.crypto.execution import flatten, run_realtime
from daytrade.crypto.study import execute

DEFAULT_CONFIG = "configs/crypto.yaml"


def main(argv: list[str] | None = None) -> int:
    def parser_factory():
        return build_parser(
            "daytrade-crypto",
            "Agente Binance (spot ou USD-M). Backtest, paper ou live, sozinho.",
            DEFAULT_CONFIG,
        )

    def backtest(cfg, args):
        execute(cfg, args.data)
        return 0

    def paper(cfg, args):
        return run_realtime(cfg, "paper", args.max_bars, args.data)

    def live(cfg, _args):
        return run_realtime(cfg, "live", None, None)

    return dispatch(
        "crypto",
        DEFAULT_CONFIG,
        argv,
        parser_factory,
        {
            "backtest": backtest,
            "paper": paper,
            "live": live,
            "flatten": flatten,
            "reset-halt": reset_halt,
            "status": show_status,
        },
    )


if __name__ == "__main__":
    raise SystemExit(main())
