"""Corretora de papel. O fill é pior que a referência pelo slippage configurado."""

from __future__ import annotations

from datetime import datetime

from daytrade.common.errors import AlreadyFlat, SafetyError
from daytrade.common.models import Fill, Instrument, OrderRequest
from daytrade.common.prices import adverse_price


class PaperBroker:
    def __init__(self, instruments: dict[str, Instrument], initial_equity: float) -> None:
        self.instruments = instruments
        self.initial_equity = initial_equity
        self.cash = float(initial_equity)
        self.net: dict[str, float] = {}
        self.avg: dict[str, float] = {}
        self.stops: dict[str, float] = {}
        self.last: dict[str, float] = {}
        self.fills_by_id: dict[str, Fill] = {}

    def mark(self, symbol: str, price: float) -> None:
        self.last[symbol] = price

    def positions(self) -> dict[str, float]:
        return {symbol: qty for symbol, qty in self.net.items() if abs(qty) > 1e-12}

    def equity(self) -> float:
        total = self.cash
        for symbol, qty in self.positions().items():
            price = self.last.get(symbol, self.avg.get(symbol, 0.0))
            inst = self.instruments[symbol]
            total += qty * (price - self.avg[symbol]) * inst.point_value
        return total

    def cancel_all(self) -> int:
        return 0

    def submit(self, order: OrderRequest, ref_price: float) -> Fill:
        cached = self.fills_by_id.get(order.client_order_id)
        if cached is not None:
            return cached
        if not order.reduce_only and order.stop_price is None:
            raise SafetyError("ordem de entrada sem stop")
        inst = self.instruments[order.symbol]
        if order.reduce_only and abs(self.net.get(order.symbol, 0.0)) < 1e-12:
            raise AlreadyFlat(order.symbol)
        price = adverse_price(order.side, ref_price, inst.slippage_ticks, inst.tick_size)
        fee = inst.fee(order.qty, price)
        fill = Fill(
            client_order_id=order.client_order_id,
            symbol=order.symbol,
            side=order.side,
            qty=order.qty,
            price=price,
            fee=fee,
            ts=order.ts,
            reduce_only=order.reduce_only,
        )
        self._apply(order, fill)
        self.fills_by_id[order.client_order_id] = fill
        self.last[order.symbol] = price
        return fill

    def force_qty(self, symbol: str, qty: float) -> None:
        """Só para teste: simula uma posição que a corretora tem e o agente não."""
        if abs(qty) < 1e-12:
            self.net.pop(symbol, None)
            return
        self.net[symbol] = qty
        self.avg.setdefault(symbol, self.last.get(symbol, 0.0))

    def restore(self, cash: float, net: dict[str, float], avg: dict[str, float]) -> None:
        self.cash = cash
        self.net = dict(net)
        self.avg = dict(avg)

    def snapshot(self) -> dict[str, object]:
        return {
            "cash": self.cash,
            "net": dict(self.net),
            "avg": dict(self.avg),
        }

    def _apply(self, order: OrderRequest, fill: Fill) -> None:
        inst = self.instruments[order.symbol]
        signed = fill.qty if fill.side == "buy" else -fill.qty
        current = self.net.get(order.symbol, 0.0)
        same_direction = current == 0 or (current > 0 and signed > 0) or (current < 0 and signed < 0)
        if same_direction and not order.reduce_only:
            new_qty = current + signed
            if abs(current) < 1e-12:
                self.avg[order.symbol] = fill.price
            else:
                self.avg[order.symbol] = (
                    abs(current) * self.avg[order.symbol] + abs(signed) * fill.price
                ) / abs(new_qty)
            self.cash -= fill.fee
            self.net[order.symbol] = new_qty
            if order.stop_price is not None:
                self.stops[order.symbol] = order.stop_price
            return
        if abs(current) < 1e-12:
            raise AlreadyFlat(order.symbol)
        entry = self.avg[order.symbol]
        direction = 1.0 if current > 0 else -1.0
        closing = min(abs(signed), abs(current))
        gross = direction * closing * (fill.price - entry) * inst.point_value
        self.cash += gross - fill.fee
        # Excesso de quantidade não inverte a posição.
        if abs(signed) > abs(current) + 1e-9:
            remaining = 0.0
        else:
            remaining = current + signed
        if abs(remaining) < 1e-9:
            self.net.pop(order.symbol, None)
            self.avg.pop(order.symbol, None)
            self.stops.pop(order.symbol, None)
        else:
            self.net[order.symbol] = remaining
