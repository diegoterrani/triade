"""Estudo: um passe contínuo e a separação dentro/fora da amostra.

A separação não reotimiza parâmetro. Ela só responde como os mesmos números
teriam se saído no período que não foi usado para olhar o resultado.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import date, timedelta
from zoneinfo import ZoneInfo

from daytrade.common.execution import ExecutionEngine
from daytrade.common.metrics import format_metrics_md, metrics_from_trades
from daytrade.common.models import Bar


EngineFactory = Callable[[], ExecutionEngine]


def first_oos_day(bars: Sequence[Bar], tz: ZoneInfo, oos_fraction: float) -> date:
    days = sorted({bar.ts.astimezone(tz).date() for bar in bars})
    if len(days) < 2:
        return days[0] if days else date.today()
    cut = int(round(len(days) * (1 - oos_fraction)))
    cut = min(max(cut, 1), len(days) - 1)
    return days[cut]


def _run(factory: EngineFactory, bars: Sequence[Bar], entry_from: date | None, entry_until: date | None) -> ExecutionEngine:
    engine = factory()
    engine.entry_from = entry_from
    engine.entry_until = entry_until
    if bars:
        engine.equity_curve.append((bars[0].ts, engine.broker.equity()))
    for bar in bars:
        if engine.process_bar(bar) == "kill":
            break
    if bars:
        engine.flatten_all("fim da amostra", ts=bars[-1].ts)
        engine.equity_curve.append((bars[-1].ts, engine.broker.equity()))
    return engine


def run_walk_forward(
    factory: EngineFactory,
    bars: Sequence[Bar],
    *,
    tz: ZoneInfo,
    oos_fraction: float,
    sharpe_periods: int,
    currency: str,
    initial_equity: float,
) -> dict[str, object]:
    oos_day = first_oos_day(bars, tz, oos_fraction)
    full = _run(factory, bars, None, None)
    inside = _run(factory, bars, None, oos_day - timedelta(days=1))
    outside = _run(factory, bars, oos_day, None)
    windows = {
        "amostra_cheia": full,
        "dentro_da_amostra": inside,
        "fora_da_amostra": outside,
    }
    report: dict[str, object] = {
        "oos_from": oos_day.isoformat(),
        "bars": len(bars),
        "start": bars[0].ts.isoformat() if bars else None,
        "end": bars[-1].ts.isoformat() if bars else None,
    }
    for name, engine in windows.items():
        block = metrics_from_trades(
            engine.trades,
            engine.equity_curve,
            initial_equity=initial_equity,
            tz=tz,
            sharpe_periods=sharpe_periods,
            currency=currency,
        )
        block["halted"] = engine.risk.state.halted
        block["halt_reason"] = engine.risk.state.halt_reason
        report[name] = block
        by_symbol: dict[str, object] = {}
        symbols = sorted({trade.symbol for trade in engine.trades})
        for symbol in symbols:
            selected = [trade for trade in engine.trades if trade.symbol == symbol]
            by_symbol[symbol] = metrics_from_trades(
                selected,
                engine.equity_curve,
                initial_equity=initial_equity,
                tz=tz,
                sharpe_periods=sharpe_periods,
                currency=currency,
            )
        report[f"{name}_por_ativo"] = by_symbol
    return report


def render_report(agent: str, strategy: dict[str, object], costs_note: str, report: dict[str, object]) -> str:
    lines = [
        f"# Estudo — {agent}",
        "",
        "Resultado histórico de um ponto de partida. Não é promessa de lucro.",
        "",
        f"- Barras: {report['bars']}",
        f"- Início: {report['start']}",
        f"- Fim: {report['end']}",
        f"- Fora da amostra a partir de: {report['oos_from']}",
        f"- Estratégia: `{strategy}`",
        f"- Custos: {costs_note}",
        "",
    ]
    for key, title in (
        ("amostra_cheia", "Amostra cheia"),
        ("dentro_da_amostra", "Dentro da amostra"),
        ("fora_da_amostra", "Fora da amostra"),
    ):
        lines.append(format_metrics_md(title, report[key]))  # type: ignore[arg-type]
    lines.append("O Sharpe usa o último equity de cada dia. Com poucos dias ele quase não diz nada.")
    lines.append("")
    return "\n".join(lines)
