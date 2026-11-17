"""Roteamento de símbolo interno para o código da corretora."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol


class SymbolRouter(Protocol):
    def venue(self, internal: str, ts: datetime) -> str:
        """Código que a corretora entende neste instante."""

    def internal(self, venue_symbol: str) -> str:
        """Volta ao símbolo estável do agente (WIN, BTCUSDT, USTEC)."""


class IdentityRouter:
    def venue(self, internal: str, ts: datetime) -> str:
        return internal

    def internal(self, venue_symbol: str) -> str:
        return venue_symbol
