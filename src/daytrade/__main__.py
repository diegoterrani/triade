"""Não sobe os três agentes. Eles são processos separados de propósito."""

from __future__ import annotations


def main() -> int:
    print(
        "Há três agentes independentes. Suba cada um no próprio processo:\n"
        "  python -m daytrade.b3 backtest|paper|live\n"
        "  python -m daytrade.crypto backtest|paper|live\n"
        "  python -m daytrade.nasdaq backtest|paper|live\n"
        "Kill switch: python -m daytrade.kill b3|crypto|nasdaq|--all\n"
        "O padrão de cada config é paper. Live exige flag e DAYTRADE_LIVE_CONFIRM."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
