"""Limites do agente. O halt de perda diária solta no dia seguinte.

O halt de drawdown máximo, por padrão, permanece até um reset manual.
Um processo novo não reabre mão sozinho depois de furar o pico de equity.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from daytrade.common.models import Instrument, Signal
from daytrade.common.prices import nearest_tick
from daytrade.common.sizing import size_by_risk


@dataclass
class RiskLimits:
    risk_per_trade_pct: float
    max_trades_per_day: int
    daily_loss_limit_pct: float
    max_drawdown_pct: float
    sticky_drawdown_halt: bool = True

    def __post_init__(self) -> None:
        if self.risk_per_trade_pct <= 0 or self.risk_per_trade_pct > 0.05:
            raise ValueError("risk_per_trade_pct tem de estar em (0, 0.05]")
        if self.max_trades_per_day < 1:
            raise ValueError("max_trades_per_day tem de ser >= 1")
        if not 0 < self.daily_loss_limit_pct <= 0.2:
            raise ValueError("daily_loss_limit_pct tem de estar em (0, 0.2]")
        if not 0 < self.max_drawdown_pct <= 0.5:
            raise ValueError("max_drawdown_pct tem de estar em (0, 0.5]")


@dataclass
class RiskState:
    day: date | None
    day_start_equity: float
    day_peak_equity: float
    equity_peak: float
    trades_today: int
    realized_pnl_today: float
    halted: bool
    sticky_halt: bool
    block_entries: bool
    halt_reason: str | None


@dataclass(frozen=True)
class RiskDecision:
    approved: bool
    qty: float
    stop_price: float | None
    reason: str


def fresh_state(equity: float) -> RiskState:
    return RiskState(
        day=None,
        day_start_equity=equity,
        day_peak_equity=equity,
        equity_peak=equity,
        trades_today=0,
        realized_pnl_today=0.0,
        halted=False,
        sticky_halt=False,
        block_entries=False,
        halt_reason=None,
    )


class RiskManager:
    def __init__(self, limits: RiskLimits, state: RiskState | None = None, equity: float = 0.0) -> None:
        self.limits = limits
        self.state = state if state is not None else fresh_state(equity)

    def is_blocked(self) -> bool:
        return self.state.halted or self.state.block_entries

    def start_day(self, day: date, equity: float) -> None:
        if self.state.day == day:
            return
        self.state.day = day
        self.state.day_start_equity = equity
        self.state.day_peak_equity = equity
        self.state.trades_today = 0
        self.state.realized_pnl_today = 0.0
        if self.state.halted and not self.state.sticky_halt:
            self.state.halted = False
            self.state.halt_reason = None

    def update_equity(self, equity: float) -> str | None:
        if equity <= 0:
            self._halt("equity não positiva", sticky=True)
            return "equity não positiva"
        self.state.equity_peak = max(self.state.equity_peak, equity)
        self.state.day_peak_equity = max(self.state.day_peak_equity, equity)
        fired: str | None = None
        drawdown = (self.state.equity_peak - equity) / self.state.equity_peak
        if drawdown >= self.limits.max_drawdown_pct:
            self._halt("drawdown máximo", sticky=self.limits.sticky_drawdown_halt)
            fired = "drawdown máximo"
        if self.state.day_start_equity > 0:
            daily = (self.state.day_start_equity - equity) / self.state.day_start_equity
            if daily >= self.limits.daily_loss_limit_pct:
                self._halt("limite diário de perda", sticky=self.state.sticky_halt)
                fired = fired or "limite diário de perda"
        return fired

    def note_entry(self) -> None:
        self.state.trades_today += 1

    def note_realized(self, pnl: float) -> None:
        self.state.realized_pnl_today += pnl

    def clear_sticky_halt(self) -> None:
        self.state.sticky_halt = False
        self.state.halted = False
        self.state.halt_reason = None

    def approve_entry(
        self,
        signal: Signal,
        equity: float,
        instrument: Instrument,
        entry: float,
        *,
        kill: bool = False,
    ) -> RiskDecision:
        if kill:
            return RiskDecision(False, 0.0, None, "kill switch")
        if self.state.block_entries:
            return RiskDecision(False, 0.0, None, "entradas bloqueadas até a reconciliação")
        if self.state.halted:
            return RiskDecision(False, 0.0, signal.stop_price, self.state.halt_reason or "agente travado")
        if signal.stop_price is None:
            return RiskDecision(False, 0.0, None, "entrada sem stop")
        stop = nearest_tick(signal.stop_price, instrument.tick_size)
        if signal.side == "buy" and stop >= entry:
            return RiskDecision(False, 0.0, stop, "stop do lado errado")
        if signal.side == "sell" and stop <= entry:
            return RiskDecision(False, 0.0, stop, "stop do lado errado")
        if abs(entry - stop) < instrument.tick_size:
            return RiskDecision(False, 0.0, stop, "distância do stop menor que um tick")
        if self.state.trades_today >= self.limits.max_trades_per_day:
            return RiskDecision(False, 0.0, stop, "máximo de trades no dia")
        qty = size_by_risk(equity, self.limits.risk_per_trade_pct, entry, stop, instrument)
        if qty <= 0:
            return RiskDecision(False, 0.0, stop, "lote mínimo estoura o risco por trade")
        return RiskDecision(True, qty, stop, "aprovado")

    def _halt(self, reason: str, *, sticky: bool) -> None:
        if not self.state.halted:
            self.state.halt_reason = reason
        self.state.halted = True
        if sticky:
            self.state.sticky_halt = True
