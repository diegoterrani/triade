"""Tamanho de posição pelo dinheiro que se aceita perder no stop.

O lote é arredondado para baixo. Se o lote mínimo já estoura o teto de risco,
a função devolve 0 e a entrada não acontece.
"""

from __future__ import annotations

from daytrade.common.models import Instrument
from daytrade.common.prices import ceil_step, floor_step


def size_by_risk(
    equity: float,
    risk_pct: float,
    entry: float,
    stop: float,
    instrument: Instrument,
) -> float:
    if equity <= 0 or risk_pct <= 0:
        return 0.0
    if instrument.point_value <= 0 or instrument.tick_size <= 0:
        return 0.0
    distance = abs(entry - stop)
    if distance < instrument.tick_size:
        return 0.0
    risk_cash = equity * risk_pct
    loss_per_unit = distance * instrument.point_value
    if loss_per_unit <= 0:
        return 0.0
    raw = risk_cash / loss_per_unit
    qty = floor_step(min(raw, instrument.max_qty), instrument.lot_step)
    if qty + 1e-12 < instrument.min_qty:
        return 0.0
    actual_risk = qty * loss_per_unit
    if actual_risk > risk_cash + 1e-6:
        return 0.0
    return qty


def size_min_notional(
    equity: float,
    risk_pct: float,
    entry: float,
    stop: float,
    instrument: Instrument,
) -> float:
    """Menor lote que cobre o notional mínimo. Se esse lote já estoura o risco, devolve 0."""
    if equity <= 0 or risk_pct <= 0 or entry <= 0 or instrument.min_notional <= 0:
        return 0.0
    distance = abs(entry - stop)
    if distance < instrument.tick_size or instrument.point_value <= 0:
        return 0.0
    raw = instrument.min_notional / (abs(entry) * instrument.point_value)
    qty = ceil_step(max(raw, instrument.min_qty), instrument.lot_step)
    if qty <= 0 or qty > instrument.max_qty + 1e-9:
        return 0.0
    if qty * distance * instrument.point_value > equity * risk_pct + 1e-6:
        return 0.0
    return qty
