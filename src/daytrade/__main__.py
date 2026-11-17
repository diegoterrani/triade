"""Não sobe os três agentes. Eles são processos separados de propósito."""

from __future__ import annotations


def main() -> int:
    print(
        "Há três agentes independentes. Suba cada um no próprio processo:\n"
        "  python -m daytrade.b3 backtest|paper|live\n"
        "  python -m daytrade.crypto backtest|paper|live\n"
        "  python -m daytrade.nasdaq backtest|paper|live\n"
        "Kill switch: python -m daytrade.kill b3|crypto|nasdaq|--all\n"
        "Analista: python -m daytrade.llm b3|crypto|nasdaq submit|status|context|set-param|enable|disable\n"
        "O padrão de cada config é paper. Live exige flag, DAYTRADE_LIVE_CONFIRM e o perfil micro_live."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
