"""Arredondamento de preço e slippage adverso. O fill nunca melhora o preço de referência."""

from __future__ import annotations

import math

from daytrade.common.models import Side


def floor_step(qty: float, step: float) -> float:
    if step <= 0:
        return float(qty)
    steps = math.floor((qty / step) + 1e-8)
    if steps <= 0:
        return 0.0
    return round(steps * step, 8)


def nearest_tick(price: float, tick: float) -> float:
    if tick <= 0:
        return float(price)
    steps = round(price / tick)
    return round(steps * tick, 10)


def ceil_tick(price: float, tick: float) -> float:
    if tick <= 0:
        return float(price)
    steps = math.ceil((price / tick) - 1e-12)
    return round(steps * tick, 10)


def floor_tick(price: float, tick: float) -> float:
    if tick <= 0:
        return float(price)
    steps = math.floor((price / tick) + 1e-12)
    return round(steps * tick, 10)


def adverse_price(side: Side, ref_price: float, slippage_ticks: float, tick: float) -> float:
    """Compra paga mais, venda recebe menos. Depois arredonda contra a ordem."""
    slip = abs(slippage_ticks) * tick
    if side == "buy":
        return ceil_tick(ref_price + slip, tick)
    return floor_tick(ref_price - slip, tick)


def net_pnl(
    qty: float,
    entry: float,
    exit_price: float,
    point_value: float,
    entry_fee: float,
    exit_fee: float,
) -> float:
    """qty com sinal: positivo comprado, negativo vendido."""
    return qty * (exit_price - entry) * point_value - entry_fee - exit_fee
