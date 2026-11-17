"""Métricas do estudo. Números curtos não viram prova de que a estratégia presta."""

from __future__ import annotations

import math
from datetime import datetime
from statistics import mean, stdev
from zoneinfo import ZoneInfo

from daytrade.common.models import Trade


def max_drawdown(equity: list[float]) -> tuple[float, float]:
    if not equity:
        return 0.0, 0.0
    peak = equity[0]
    worst = 0.0
    worst_pct = 0.0
    for value in equity:
        peak = max(peak, value)
        gap = peak - value
        worst = max(worst, gap)
        if peak > 0:
            worst_pct = max(worst_pct, gap / peak)
    return worst, worst_pct


def daily_equity(curve: list[tuple[datetime, float]], tz: ZoneInfo) -> list[float]:
    last: dict[object, float] = {}
    order: list[object] = []
    for ts, equity in curve:
        day = ts.astimezone(tz).date()
        if day not in last:
            order.append(day)
        last[day] = equity
    return [last[day] for day in order]


def _sharpe(equity: list[float], periods: int) -> float | None:
    if len(equity) < 3:
        return None
    returns = [equity[i] / equity[i - 1] - 1 for i in range(1, len(equity)) if equity[i - 1] > 0]
    if len(returns) < 2:
        return None
    dispersion = stdev(returns)
    if dispersion == 0:
        return 0.0
    return mean(returns) / dispersion * math.sqrt(periods)


def metrics_from_trades(
    trades: list[Trade],
    curve: list[tuple[datetime, float]],
    *,
    initial_equity: float,
    tz: ZoneInfo,
    sharpe_periods: int,
    currency: str,
) -> dict[str, object]:
    wins = [trade.pnl for trade in trades if trade.pnl > 0]
    losses = [trade.pnl for trade in trades if trade.pnl < 0]
    net = sum(trade.pnl for trade in trades)
    fees = sum(trade.fees for trade in trades)
    gross_win = sum(wins)
    gross_loss = abs(sum(losses))
    equity_values = [point for _, point in curve] or [initial_equity]
    drawdown, drawdown_pct = max_drawdown(equity_values)
    daily = daily_equity(curve, tz)
    count = len(trades)
    return {
        "trades": count,
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": (len(wins) / count) if count else 0.0,
        "profit_factor": (gross_win / gross_loss) if gross_loss else None,
        "max_drawdown": drawdown,
        "max_drawdown_pct": drawdown_pct,
        "sharpe": _sharpe(daily, sharpe_periods),
        "expectancy": (net / count) if count else 0.0,
        "net_pnl": net,
        "fees": fees,
        "avg_win": (gross_win / len(wins)) if wins else 0.0,
        "avg_loss": (sum(losses) / len(losses)) if losses else 0.0,
        "initial_equity": initial_equity,
        "ending_equity": equity_values[-1],
        "currency": currency,
        "days": len(daily),
    }


def format_metrics_md(title: str, block: dict[str, object]) -> str:
    sharpe = block["sharpe"]
    profit_factor = block["profit_factor"]
    sharpe_txt = "n/d" if sharpe is None else f"{float(sharpe):.2f}"
    pf_txt = "sem perdas" if profit_factor is None else f"{float(profit_factor):.2f}"
    return "\n".join(
        [
            f"### {title}",
            "",
            f"- Trades: {block['trades']} (ganhos {block['wins']}, perdas {block['losses']})",
            f"- Taxa de acerto: {float(block['win_rate']):.1%}",
            f"- Fator de lucro: {pf_txt}",
            f"- Drawdown máximo: {float(block['max_drawdown']):.2f} {block['currency']} ({float(block['max_drawdown_pct']):.1%})",
            f"- Sharpe ({block['days']} dias): {sharpe_txt}",
            f"- Expectativa por trade: {float(block['expectancy']):.2f} {block['currency']}",
            f"- PnL líquido: {float(block['net_pnl']):.2f} {block['currency']}",
            f"- Custos: {float(block['fees']):.2f} {block['currency']}",
            f"- Equity final: {float(block['ending_equity']):.2f} {block['currency']}",
            "",
        ]
    )
