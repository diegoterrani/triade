"""Protocolo de estratégia. Cada agente registra as suas e ignora as dos outros."""

from __future__ import annotations

from typing import Protocol

from daytrade.common.models import Bar, Position, Signal


class Strategy(Protocol):
    name: str

    def reset(self) -> None:
        """Zera o estado interno. Um backtest novo não herda o anterior."""

    def on_bar(self, bar: Bar, position: Position | None) -> list[Signal]:
        """Chamado no fechamento da barra. Só pode usar esta barra e as anteriores."""

    def describe(self) -> dict[str, object]:
        """Parâmetros para o relatório. Sem segredos."""
