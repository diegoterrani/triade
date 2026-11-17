"""Roda o estudo dos três agentes e junta um relatório.

O modo de reversão à VWAP do NASDAQ roda à parte, sem alterar o config padrão.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

from daytrade.b3.study import execute as b3_study
from daytrade.common.config import load_config, resolve_path
from daytrade.crypto.study import execute as crypto_study
from daytrade.nasdaq.study import execute as nasdaq_study


def _snippet(path: Path) -> str:
    payload = json.loads(path.read_text(encoding="utf-8"))
    full = payload["amostra_cheia"]
    oos = payload["fora_da_amostra"]
    sharpe = full["sharpe"]
    sharpe_txt = "n/d" if sharpe is None else f"{sharpe:.2f}"
    oos_sharpe = oos["sharpe"]
    oos_txt = "n/d" if oos_sharpe is None else f"{oos_sharpe:.2f}"
    pf = full["profit_factor"]
    pf_txt = "sem perdas" if pf is None else f"{pf:.2f}"
    lines = [
        f"### {payload['agent']} — `{payload['strategy']['name']}`",
        "",
        f"- Fonte: {payload['data']['source']}",
        f"- Período: {payload['start']} → {payload['end']} ({payload['bars']} barras)",
        f"- Fora da amostra desde: {payload['oos_from']}",
        f"- Amostra cheia: {full['trades']} trades, acerto {full['win_rate']:.1%}, "
        f"fator de lucro {pf_txt}, PnL {full['net_pnl']:.2f} {full['currency']}, "
        f"drawdown {full['max_drawdown_pct']:.1%}, Sharpe {sharpe_txt}",
        f"- Fora da amostra: {oos['trades']} trades, PnL {oos['net_pnl']:.2f} {oos['currency']}, "
        f"Sharpe {oos_txt}",
    ]
    if full.get("halted"):
        lines.append(
            f"- Amostra cheia travou: {full.get('halt_reason')}. "
            "O passe fora da amostra é outro processo, com equity nova."
        )
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    b3_study(load_config("configs/b3.yaml"))
    crypto_study(load_config("configs/crypto.yaml"))
    nasdaq_cfg = load_config("configs/nasdaq.yaml")
    nasdaq_study(nasdaq_cfg, artifact_name="nasdaq_orb")
    vwap = copy.deepcopy(nasdaq_cfg)
    vwap["strategy"]["name"] = "vwap_mean_reversion"
    nasdaq_study(vwap, artifact_name="nasdaq_vwap_mr")
    folder = resolve_path("artifacts/backtests")
    parts = [
        "# Amostra de backtest",
        "",
        "Números de um ponto de partida. Não são promessa de lucro e não foram otimizados contra esta amostra.",
        "",
        _snippet(folder / "b3.json"),
        _snippet(folder / "crypto.json"),
        _snippet(folder / "nasdaq_orb.json"),
        _snippet(folder / "nasdaq_vwap_mr.json"),
        "B3 e NASDAQ usam série sintética. Cripto usa klines públicos da Binance.",
        "",
    ]
    text = "\n".join(parts)
    (folder / "RELATORIO.md").write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
