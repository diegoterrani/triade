"""Agente B3. Processo próprio para WIN e WDO. Não sobe os outros agentes."""

from __future__ import annotations

from daytrade.b3.execution import flatten, run_realtime
from daytrade.b3.study import execute
from daytrade.common.app import dispatch, reset_halt, show_status
from daytrade.common.cli import build_parser

DEFAULT_CONFIG = "configs/b3.yaml"


def main(argv: list[str] | None = None) -> int:
    def parser_factory():
        return build_parser(
            "daytrade-b3",
            "Agente B3 (WIN e WDO). Backtest, paper ou live, sozinho.",
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
        "b3",
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
