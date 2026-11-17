"""A especificação da corretora manda no tamanho do contrato. Config furado não opera."""

from __future__ import annotations

from daytrade.common.errors import SafetyError


def assert_point_value(
    *,
    symbol: str,
    config_point_value: float,
    broker_tick_value: float,
    broker_tick_size: float,
    tolerance: float = 0.05,
) -> float:
    if broker_tick_size <= 0 or broker_tick_value < 0:
        raise SafetyError(f"{symbol}: tick do terminal inválido")
    if config_point_value <= 0:
        raise SafetyError(f"{symbol}: point_value do config inválido")
    broker_point = broker_tick_value / broker_tick_size
    gap = abs(broker_point - config_point_value) / config_point_value
    if gap > tolerance:
        raise SafetyError(
            f"{symbol}: point value do terminal ({broker_point:.6f}) difere do config "
            f"({config_point_value:.6f}) em {gap:.1%}. Ajuste o YAML à especificação do símbolo "
            "antes de mandar ordem."
        )
    return broker_point


def read_terminal_spec(
    symbol: str,
    *,
    volume_min: float | None,
    volume_step: float | None,
    tick_size: float | None,
    tick_value: float | None,
) -> dict[str, float]:
    """Lê o lote mínimo do terminal. Sem esses números o micro_live não opera."""
    if volume_min is None or volume_min <= 0 or volume_step is None or volume_step <= 0:
        raise SafetyError(
            f"{symbol}: lote mínimo ou passo ilegível no terminal. "
            "O perfil micro_live não chuta esse número."
        )
    if tick_size is None or tick_size <= 0 or tick_value is None or tick_value < 0:
        raise SafetyError(
            f"{symbol}: tick ou valor do tick ilegível no terminal. "
            "O perfil micro_live não opera sem o point value da corretora."
        )
    return {
        "min_qty": float(volume_min),
        "lot_step": float(volume_step),
        "tick_size": float(tick_size),
        "point_value": float(tick_value) / float(tick_size),
    }
