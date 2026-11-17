"""Agente NASDAQ (USTEC na IC Markets). Processo próprio."""

from __future__ import annotations

from daytrade.common.app import dispatch, reset_halt, show_status
from daytrade.common.cli import build_parser
from daytrade.nasdaq.execution import flatten, run_realtime
from daytrade.nasdaq.study import execute

DEFAULT_CONFIG = "configs/nasdaq.yaml"


def main(argv: list[str] | None = None) -> int:
    def parser_factory():
        return build_parser(
            "daytrade-nasdaq",
            "Agente NASDAQ 100 (USTEC via MT5 na IC Markets).",
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
        "nasdaq",
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
