"""Modelos compartilhados. O preço de um mercado nunca se mistura com o de outro."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

Side = Literal["buy", "sell"]
SignalSide = Literal["buy", "sell", "flat"]
Mode = Literal["backtest", "paper", "live"]


@dataclass(frozen=True)
class Instrument:
    """Especificação negociável. point_value é a moeda ganha por 1.0 de preço e 1 lote."""

    symbol: str
    root: str
    tick_size: float
    point_value: float
    lot_step: float
    min_qty: float
    currency: str
    fee_per_unit_side: float = 0.0
    fee_rate_side: float = 0.0
    slippage_ticks: float = 0.0
    max_qty: float = 1.0
    min_notional: float = 0.0

    def fee(self, qty: float, price: float) -> float:
        notional = abs(price) * self.point_value
        return abs(qty) * self.fee_per_unit_side + abs(qty) * notional * self.fee_rate_side


@dataclass(frozen=True)
class Bar:
    symbol: str
    ts: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    timeframe: str
    funding_rate: float | None = None

    def __post_init__(self) -> None:
        if self.ts.tzinfo is None:
            raise ValueError(f"barra {self.symbol} em {self.ts} está sem fuso horário")
        if self.high < self.low:
            raise ValueError(f"barra {self.symbol} com máxima abaixo da mínima")


@dataclass(frozen=True)
class Signal:
    symbol: str
    ts: datetime
    side: SignalSide
    reason: str
    strategy: str
    stop_price: float | None = None
    target_price: float | None = None
    immediate: bool = False
    strength: float = 1.0
    source: str = "python"
    requested_qty: float | None = None
    limit_price: float | None = None
    max_hold_minutes: int | None = None
    client_order_id: str | None = None
    rationale: str = ""


@dataclass(frozen=True)
class Position:
    symbol: str
    qty: float
    avg_price: float
    stop_price: float
    opened_at: datetime
    strategy: str
    entry_reason: str
    entry_fee: float
    contract: str
    client_order_id: str
    target_price: float | None = None
    source: str = "python"
    max_hold_until: datetime | None = None

    @property
    def side(self) -> Side:
        return "buy" if self.qty > 0 else "sell"


@dataclass(frozen=True)
class OrderRequest:
    client_order_id: str
    symbol: str
    side: Side
    qty: float
    reason: str
    strategy: str
    ts: datetime
    stop_price: float | None = None
    reduce_only: bool = False
    contract: str = ""
    source: str = "python"


@dataclass(frozen=True)
class Fill:
    client_order_id: str
    symbol: str
    side: Side
    qty: float
    price: float
    fee: float
    ts: datetime
    reduce_only: bool


@dataclass(frozen=True)
class Trade:
    symbol: str
    contract: str
    side: Side
    qty: float
    entry_ts: datetime
    exit_ts: datetime
    entry_price: float
    exit_price: float
    pnl: float
    fees: float
    entry_reason: str
    exit_reason: str
    strategy: str
    source: str = "python"
