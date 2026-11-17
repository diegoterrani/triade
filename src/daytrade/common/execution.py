"""Execução: uma ordem de entrada carrega stop, o id não repete, e divergência não reabre mão.

O backtest e o paper passam por aqui. O modo live usa a mesma classe com outra corretora.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, replace
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Callable
from zoneinfo import ZoneInfo

from daytrade.common.errors import AlreadyFlat, Disconnect, EntryRolledBack, SafetyError
from daytrade.common.ids import client_order_id
from daytrade.common.journal import Journal
from daytrade.common.killswitch import KillSwitch
from daytrade.common.llm_control import apply_params, read_control, write_event, write_result
from daytrade.common.llm_orders import hold_deadline, signal_from_order
from daytrade.common.logging_setup import log_event
from daytrade.common.models import Bar, Instrument, OrderRequest, Position, Signal, Trade
from daytrade.common.notify import Notifier, NullNotifier
from daytrade.common.prices import adverse_price, floor_tick, ceil_tick, net_pnl
from daytrade.common.reconcile import ReconcileResult, reconcile
from daytrade.common.risk import RiskManager
from daytrade.common.strategy import Strategy


ContractResolver = Callable[[str, datetime], str]


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _exit_kind(reason: str) -> str:
    text = reason.lower()
    if "stop" in text:
        return "stop"
    if "alvo" in text:
        return "target"
    return "flatten"


def _stop_reference(position: Position, bar: Bar) -> float | None:
    if position.qty > 0 and bar.low <= position.stop_price:
        if bar.open < position.stop_price:
            return bar.open
        return position.stop_price
    if position.qty < 0 and bar.high >= position.stop_price:
        if bar.open > position.stop_price:
            return bar.open
        return position.stop_price
    return None


def _target_reference(position: Position, bar: Bar) -> float | None:
    target = position.target_price
    if target is None:
        return None
    if position.qty > 0 and bar.high >= target:
        return target
    if position.qty < 0 and bar.low <= target:
        return target
    return None


class ExecutionEngine:
    def __init__(
        self,
        *,
        agent: str,
        broker: object,
        risk: RiskManager,
        instruments: dict[str, Instrument],
        strategies: dict[str, Strategy],
        journal: Journal,
        risk_tz: ZoneInfo,
        resolve_contract: ContractResolver | None = None,
        kill: KillSwitch | None = None,
        logger: logging.Logger | None = None,
        notifier: Notifier | None = None,
        emergency_stop_pct: float = 0.01,
        persist_path: Path | None = None,
        llm_dir: Path | None = None,
        param_bounds: dict | None = None,
        analyst_enabled: bool = True,
        volume_spike_multiple: float = 2.0,
    ) -> None:
        self.agent = agent
        self.broker = broker
        self.risk = risk
        self.instruments = instruments
        self.strategies = strategies
        self.journal = journal
        self.risk_tz = risk_tz
        self.resolve_contract = resolve_contract or (lambda symbol, _ts: symbol)
        self.kill = kill
        self.logger = logger or _null_logger(agent)
        self.notifier = notifier or NullNotifier()
        self.emergency_stop_pct = emergency_stop_pct
        self.persist_path = persist_path
        self.llm_dir = llm_dir
        self.param_bounds = param_bounds or {}
        self.analyst_enabled = analyst_enabled
        self.volume_spike_multiple = volume_spike_multiple
        self.positions: dict[str, Position] = {}
        self.pending: dict[str, Signal] = {}
        self.llm_pending: dict[str, Signal] = {}
        self.llm_done: set[str] = set()
        self.recent_bars: list[Bar] = []
        self._volumes: dict[str, list[float]] = {}
        self.seen: set[str] = set()
        self.trades: list[Trade] = []
        self.equity_curve: list[tuple[datetime, float]] = []
        self.last_prices: dict[str, float] = {}
        self.block_entries = False
        self.entry_from: date | None = None
        self.entry_until: date | None = None
        self.last_bar_ts: datetime | None = None
        self._halt_logged: str | None = None

    def process_bar(self, bar: Bar) -> str:
        kill_reason = self.kill.tripped() if self.kill is not None else None
        if kill_reason:
            self.flatten_all(f"kill switch: {kill_reason}", ts=bar.ts)
            self.journal.write("kill", motivo=kill_reason, symbol=bar.symbol)
            self.notifier.send(f"{self.agent}: kill switch. {kill_reason}")
            return "kill"
        self.last_prices[bar.symbol] = bar.open
        self.broker.mark(bar.symbol, bar.open)
        day = bar.ts.astimezone(self.risk_tz).date()
        equity = self._equity()
        self.risk.start_day(day, equity)
        if not self.risk.state.halted:
            self._halt_logged = None
        self._log_halt(self.risk.update_equity(equity))
        self._apply_live_params()
        pending = self.pending.pop(bar.symbol, None)
        if pending is not None:
            self._act_pending(pending, bar)
        llm_pending = self.llm_pending.pop(bar.symbol, None)
        if llm_pending is not None:
            if bar.symbol in self.positions:
                self._reject(llm_pending, f"símbolo ocupado pela fonte {self.positions[bar.symbol].source}; uma mão por símbolo, sem netting")
            else:
                self._act_pending(llm_pending, bar)
        self._protect(bar)
        self.last_prices[bar.symbol] = bar.close
        self.broker.mark(bar.symbol, bar.close)
        self._log_halt(self.risk.update_equity(self._equity()))
        strategy = self.strategies.get(bar.symbol)
        if strategy is not None:
            held = self.positions.get(bar.symbol)
            visible = held if held is None or held.source == "python" else None
            signals = strategy.on_bar(bar, visible)
            for signal in signals:
                self._handle_signal(signal, bar)
        self._note_volume(bar)
        self._remember_bar(bar)
        self._drain_llm(bar)
        self.equity_curve.append((bar.ts, self._equity()))
        self.last_bar_ts = bar.ts
        return "ok"

    def on_disconnect(self, detail: str) -> None:
        self.pending.clear()
        self.llm_pending.clear()
        self.block_entries = True
        self.risk.state.block_entries = True
        self.journal.write("disconnect", detalhe=detail)
        log_event(self.logger, logging.ERROR, "desconexão; sinais pendentes descartados", detalhe=detail)
        self.notifier.send(f"{self.agent}: desconexão. Sem novas entradas até reconciliar. {detail}")

    def reconcile_and_adopt(self) -> ReconcileResult:
        local = {symbol: position.qty for symbol, position in self.positions.items()}
        remote = self.broker.positions()
        result = reconcile(local, remote)
        if result.ok:
            self.block_entries = False
            self.risk.state.block_entries = False
            self.journal.write("reconcile", ok=True)
            log_event(self.logger, logging.INFO, "reconciliação ok; nenhuma reentrada do sinal antigo")
            return result
        self.block_entries = True
        self.risk.state.block_entries = True
        now = _utc_now()
        for symbol in result.adopted:
            self._adopt(symbol, remote[symbol], now)
        for symbol, qty in remote.items():
            if abs(qty) < 1e-12:
                self.positions.pop(symbol, None)
                continue
            position = self.positions.get(symbol)
            if position is not None and abs(position.qty - qty) > 1e-8:
                self.positions[symbol] = replace(position, qty=qty)
        for symbol in list(self.positions):
            if abs(remote.get(symbol, 0.0)) < 1e-12:
                self.positions.pop(symbol, None)
        self.journal.write("reconcile", ok=False, divergencias=result.mismatches, adotados=result.adopted)
        log_event(
            self.logger,
            logging.CRITICAL,
            "reconciliação divergente; novas entradas bloqueadas",
            divergencias=result.mismatches,
        )
        self.notifier.send(f"{self.agent}: divergência com a corretora. Entradas bloqueadas.")
        return result

    def flatten_all(self, reason: str, ts: datetime | None = None) -> None:
        when = ts or _utc_now()
        self.pending.clear()
        self.llm_pending.clear()
        cancelled = 0
        try:
            cancelled = int(self.broker.cancel_all())
        except Disconnect as exc:
            self.journal.write("cancel_failed", erro=str(exc))
            log_event(self.logger, logging.ERROR, "falha ao cancelar ordens", erro=str(exc))
        symbols = set(self.positions) | set(self.broker.positions())
        for symbol in sorted(symbols):
            price = self.last_prices.get(symbol)
            if price is None:
                price = getattr(self.broker, "last", {}).get(symbol)
            if price is None and symbol in self.positions:
                price = self.positions[symbol].avg_price
            if price is None:
                self.journal.write("flatten_sem_preco", symbol=symbol, motivo=reason)
                continue
            self._flatten(symbol, price, when, reason)
        self.journal.write("flatten_all", motivo=reason, canceladas=cancelled)

    def persist(self) -> None:
        if self.persist_path is None:
            return
        self.persist_path.parent.mkdir(parents=True, exist_ok=True)
        payload = self.export_state()
        temporary = self.persist_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(self.persist_path)

    def export_state(self) -> dict[str, object]:
        broker_state = self.broker.snapshot() if hasattr(self.broker, "snapshot") else {}
        return {
            "agent": self.agent,
            "equity_peak": self.risk.state.equity_peak,
            "day": self.risk.state.day.isoformat() if self.risk.state.day else None,
            "day_start_equity": self.risk.state.day_start_equity,
            "day_peak_equity": self.risk.state.day_peak_equity,
            "trades_today": self.risk.state.trades_today,
            "realized_pnl_today": self.risk.state.realized_pnl_today,
            "halted": self.risk.state.halted,
            "sticky_halt": self.risk.state.sticky_halt,
            "halt_reason": self.risk.state.halt_reason,
            "block_entries": self.block_entries,
            "trades_by_source": dict(self.risk.state.trades_by_source),
            "pnl_by_source": dict(self.risk.state.pnl_by_source),
            "source_halted": dict(self.risk.state.source_halted),
            "seen": sorted(self.seen),
            "positions": [_position_dict(position) for position in self.positions.values()],
            "broker": broker_state,
        }

    def restore_state(self, payload: dict) -> None:
        state = self.risk.state
        state.equity_peak = float(payload.get("equity_peak", state.equity_peak))
        day = payload.get("day")
        state.day = date.fromisoformat(day) if day else None
        state.day_start_equity = float(payload.get("day_start_equity", state.day_start_equity))
        state.day_peak_equity = float(payload.get("day_peak_equity", state.day_peak_equity))
        state.trades_today = int(payload.get("trades_today", 0))
        state.realized_pnl_today = float(payload.get("realized_pnl_today", 0.0))
        state.halted = bool(payload.get("halted", False))
        state.sticky_halt = bool(payload.get("sticky_halt", False))
        state.halt_reason = payload.get("halt_reason")
        self.block_entries = bool(payload.get("block_entries", False))
        state.block_entries = self.block_entries
        state.trades_by_source = {str(key): int(value) for key, value in (payload.get("trades_by_source") or {}).items()}
        state.pnl_by_source = {str(key): float(value) for key, value in (payload.get("pnl_by_source") or {}).items()}
        state.source_halted = {str(key): str(value) for key, value in (payload.get("source_halted") or {}).items()}
        self.seen = set(payload.get("seen", []))
        self.positions = {}
        for raw in payload.get("positions", []):
            position = _position_from(raw)
            self.positions[position.symbol] = position
            self.last_prices[position.symbol] = position.avg_price
        broker_state = payload.get("broker") or {}
        if broker_state and hasattr(self.broker, "restore"):
            self.broker.restore(
                float(broker_state.get("cash", self.broker.initial_equity)),
                dict(broker_state.get("net") or {}),
                dict(broker_state.get("avg") or {}),
            )

    def _act_pending(self, signal: Signal, bar: Bar) -> None:
        if signal.side == "flat":
            held = self.positions.get(signal.symbol)
            if held is not None and held.source == signal.source:
                self._flatten(signal.symbol, bar.open, bar.ts, signal.reason)
            return
        if signal.limit_price is not None:
            if signal.ts.astimezone(self.risk_tz).date() != bar.ts.astimezone(self.risk_tz).date():
                self._reject(signal, "ordem limite expirou no dia")
                return
            touched = bar.low <= signal.limit_price if signal.side == "buy" else bar.high >= signal.limit_price
            if not touched:
                self._queue(signal)
                return
            self._try_entry(signal, signal.limit_price, bar.ts)
            return
        self._try_entry(signal, bar.open, bar.ts)

    def _queue(self, signal: Signal) -> None:
        if signal.source == "llm":
            self.llm_pending[signal.symbol] = signal
        else:
            self.pending[signal.symbol] = signal

    def _handle_signal(self, signal: Signal, bar: Bar) -> None:
        self.journal.write(
            "signal",
            symbol=signal.symbol,
            side=signal.side,
            reason=signal.reason,
            strategy=signal.strategy,
            stop=signal.stop_price,
            target=signal.target_price,
            source=signal.source,
            rationale=signal.rationale or signal.reason,
        )
        if signal.source == "python" and signal.side in ("buy", "sell"):
            self._event("range_break", symbol=signal.symbol, side=signal.side, rationale=signal.reason)
        log_event(
            self.logger,
            logging.INFO,
            "sinal",
            symbol=signal.symbol,
            side=signal.side,
            reason=signal.reason,
            stop=signal.stop_price,
        )
        if signal.side == "flat":
            held = self.positions.get(signal.symbol)
            if held is None:
                return
            if held.source != signal.source:
                self._reject(signal, f"saída ignorada: a mão é da fonte {held.source}")
                return
            if signal.immediate:
                self._flatten(signal.symbol, bar.close, bar.ts, signal.reason)
            else:
                self._queue(signal)
            return
        if self._entries_disabled() and signal.source in ("python", "llm"):
            self._reject(signal, "agente desligado pelo analista; entradas novas bloqueadas")
            return
        if self.block_entries or self.risk.is_blocked():
            self._reject(signal, self.risk.state.halt_reason or "entradas bloqueadas até a reconciliação")
            return
        held = self.positions.get(signal.symbol)
        if held is not None:
            if held.source != signal.source:
                self._reject(signal, f"símbolo ocupado pela fonte {held.source}; uma mão por símbolo, sem netting")
            elif signal.source == "llm":
                self._reject(signal, "já existe mão desta fonte neste símbolo")
            return
        if signal.immediate:
            self._try_entry(signal, bar.close, bar.ts)
        else:
            self._queue(signal)

    def _try_entry(self, signal: Signal, ref_price: float, ts: datetime) -> None:
        if signal.side not in ("buy", "sell"):
            return
        if self.block_entries or self.risk.state.block_entries:
            self._reject(signal, "entradas bloqueadas até a reconciliação")
            return
        day = signal.ts.astimezone(self.risk_tz).date()
        if self.entry_from is not None and day < self.entry_from:
            return
        if self.entry_until is not None and day > self.entry_until:
            return
        instrument = self.instruments[signal.symbol]
        if signal.stop_price is None:
            self._reject(signal, "entrada sem stop")
            return
        worst = adverse_price(signal.side, ref_price, instrument.slippage_ticks, instrument.tick_size)
        decision = self.risk.approve_entry(
            signal,
            self._equity(),
            instrument,
            worst,
            kill=bool(self.kill and self.kill.tripped()),
        )
        if not decision.approved or decision.stop_price is None:
            self._reject(signal, decision.reason)
            return
        contract = self.resolve_contract(signal.symbol, ts)
        order = OrderRequest(
            client_order_id=signal.client_order_id or client_order_id(self.agent, contract, signal.ts, signal.side, "entry"),
            symbol=signal.symbol,
            side=signal.side,  # type: ignore[arg-type]
            qty=decision.qty,
            reason=signal.reason,
            strategy=signal.strategy,
            ts=ts,
            stop_price=decision.stop_price,
            reduce_only=False,
            contract=contract,
            source=signal.source,
        )
        try:
            fill = self._submit_once(order, ref_price)
        except EntryRolledBack as exc:
            self._reject(signal, str(exc))
            return
        except SafetyError as exc:
            self._reject(signal, str(exc))
            return
        if fill is None:
            return
        wrong_side = (signal.side == "buy" and decision.stop_price >= fill.price) or (
            signal.side == "sell" and decision.stop_price <= fill.price
        )
        qty = fill.qty if signal.side == "buy" else -fill.qty
        self.positions[signal.symbol] = Position(
            symbol=signal.symbol,
            qty=qty,
            avg_price=fill.price,
            stop_price=decision.stop_price,
            opened_at=fill.ts,
            strategy=signal.strategy,
            entry_reason=signal.reason,
            entry_fee=fill.fee,
            contract=contract,
            client_order_id=fill.client_order_id,
            target_price=signal.target_price,
            source=signal.source,
            max_hold_until=hold_deadline(fill.ts, signal.max_hold_minutes),
        )
        self.risk.note_entry(signal.source)
        self.journal.write(
            "fill",
            symbol=signal.symbol,
            contract=contract,
            side=signal.side,
            qty=fill.qty,
            price=fill.price,
            stop=decision.stop_price,
            fee=fill.fee,
            reason=signal.reason,
            client_order_id=fill.client_order_id,
            source=signal.source,
        )
        log_event(
            self.logger,
            logging.INFO,
            "entrada preenchida",
            symbol=signal.symbol,
            contract=contract,
            side=signal.side,
            qty=fill.qty,
            price=fill.price,
            stop=decision.stop_price,
        )
        self.notifier.send(
            f"{self.agent}: {signal.side} {fill.qty} {contract} @ {fill.price} stop {decision.stop_price}. {signal.reason}"
        )
        if wrong_side:
            self.journal.write("emergency", symbol=signal.symbol, motivo="stop do lado errado depois do fill")
            self._flatten(signal.symbol, fill.price, ts, "stop do lado errado depois do fill")

    def _protect(self, bar: Bar) -> None:
        position = self.positions.get(bar.symbol)
        if position is None:
            return
        if position.max_hold_until is not None and bar.ts >= position.max_hold_until:
            self._flatten(bar.symbol, bar.close, bar.ts, "tempo máximo da mão")
            return
        stop_ref = _stop_reference(position, bar)
        if stop_ref is not None:
            self._flatten(bar.symbol, stop_ref, bar.ts, "stop")
            return
        target_ref = _target_reference(position, bar)
        if target_ref is not None:
            self._flatten(bar.symbol, target_ref, bar.ts, "alvo")

    def _flatten(self, symbol: str, ref_price: float, ts: datetime, reason: str) -> None:
        position = self.positions.get(symbol)
        remote_qty = float(self.broker.positions().get(symbol, 0.0))
        qty_signed = position.qty if position is not None else remote_qty
        if abs(qty_signed) < 1e-12:
            self.positions.pop(symbol, None)
            return
        side = "sell" if qty_signed > 0 else "buy"
        contract = position.contract if position is not None else self.resolve_contract(symbol, ts)
        order = OrderRequest(
            client_order_id=client_order_id(self.agent, contract, ts, side, _exit_kind(reason)),
            symbol=symbol,
            side=side,
            qty=abs(qty_signed),
            reason=reason,
            strategy=position.strategy if position is not None else self.agent,
            ts=ts,
            stop_price=None,
            reduce_only=True,
            contract=contract,
        )
        try:
            fill = self._submit_once(order, ref_price)
        except AlreadyFlat:
            self.positions.pop(symbol, None)
            self.journal.write("already_flat", symbol=symbol, motivo=reason)
            return
        except SafetyError as exc:
            self.journal.write("flatten_failed", symbol=symbol, motivo=reason, erro=str(exc))
            log_event(self.logger, logging.ERROR, "falha ao zerar", symbol=symbol, erro=str(exc))
            return
        if fill is None:
            return
        instrument = self.instruments[symbol]
        if position is None:
            self.journal.write(
                "fill",
                symbol=symbol,
                contract=contract,
                side=side,
                qty=fill.qty,
                price=fill.price,
                reason=reason,
                client_order_id=fill.client_order_id,
            )
            return
        pnl = net_pnl(
            position.qty,
            position.avg_price,
            fill.price,
            instrument.point_value,
            position.entry_fee,
            fill.fee,
        )
        trade = Trade(
            symbol=symbol,
            contract=contract,
            side=position.side,
            qty=abs(position.qty),
            entry_ts=position.opened_at,
            exit_ts=fill.ts,
            entry_price=position.avg_price,
            exit_price=fill.price,
            pnl=pnl,
            fees=position.entry_fee + fill.fee,
            entry_reason=position.entry_reason,
            exit_reason=reason,
            strategy=position.strategy,
            source=position.source,
        )
        self.trades.append(trade)
        self.risk.note_realized(pnl, position.source)
        self.positions.pop(symbol, None)
        self.journal.write(
            "trade",
            symbol=symbol,
            contract=contract,
            side=trade.side,
            qty=trade.qty,
            entry=trade.entry_price,
            exit=trade.exit_price,
            pnl=round(pnl, 6),
            fees=round(trade.fees, 6),
            entry_reason=trade.entry_reason,
            exit_reason=reason,
            client_order_id=fill.client_order_id,
            source=position.source,
        )
        log_event(
            self.logger,
            logging.INFO,
            "saída preenchida",
            symbol=symbol,
            contract=contract,
            pnl=round(pnl, 2),
            motivo=reason,
        )
        self.notifier.send(f"{self.agent}: saída {contract} pnl {pnl:.2f} ({reason})")

    def _submit_once(self, order: OrderRequest, ref_price: float):
        if order.client_order_id in self.seen:
            self.journal.write("idempotent", client_order_id=order.client_order_id)
            return None
        if not order.reduce_only and order.stop_price is None:
            raise SafetyError("ordem de entrada sem stop")
        fill = self.broker.submit(order, ref_price)
        self.seen.add(order.client_order_id)
        return fill

    def _adopt(self, symbol: str, qty: float, ts: datetime) -> None:
        price = self.last_prices.get(symbol) or getattr(self.broker, "last", {}).get(symbol)
        if price is None:
            self.journal.write("adopt_sem_preco", symbol=symbol, qty=qty)
            return
        stop = self._emergency_stop(symbol, qty, price)
        self.positions[symbol] = Position(
            symbol=symbol,
            qty=qty,
            avg_price=price,
            stop_price=stop,
            opened_at=ts,
            strategy="reconcile",
            entry_reason="posição encontrada na corretora; sem reentrada",
            entry_fee=0.0,
            contract=self.resolve_contract(symbol, ts),
            client_order_id="adopted",
            source="broker",
        )
        attach = getattr(self.broker, "attach_stop", None)
        if attach is not None:
            try:
                attach(symbol, qty, stop)
            except SafetyError as exc:
                self.journal.write("emergency_stop_failed", symbol=symbol, erro=str(exc))
                self._flatten(symbol, price, ts, "stop de emergência falhou")
                return
        self.journal.write("adopted", symbol=symbol, qty=qty, stop=stop, preco=price)
        log_event(
            self.logger,
            logging.CRITICAL,
            "posição adotada da corretora com stop de emergência; sem aumentar o tamanho",
            symbol=symbol,
            qty=qty,
            stop=stop,
        )

    def _emergency_stop(self, symbol: str, qty: float, price: float) -> float:
        instrument = self.instruments[symbol]
        if qty > 0:
            return floor_tick(price * (1 - self.emergency_stop_pct), instrument.tick_size)
        return ceil_tick(price * (1 + self.emergency_stop_pct), instrument.tick_size)

    def _reject(self, signal: Signal, reason: str) -> None:
        self.journal.write(
            "reject",
            symbol=signal.symbol,
            side=signal.side,
            reason=reason,
            sinal=signal.reason,
            source=signal.source,
            rationale=signal.rationale or signal.reason,
        )
        if signal.source == "llm" and signal.client_order_id and self.llm_dir is not None:
            self.llm_done.add(signal.client_order_id)
            write_result(self.llm_dir.parent, signal.client_order_id, "recusada", reason)
            inbox = self.llm_dir / "inbox" / f"{signal.client_order_id}.json"
            if inbox.exists():
                inbox.unlink()
        log_event(
            self.logger,
            logging.INFO,
            "sinal recusado",
            symbol=signal.symbol,
            side=signal.side,
            reason=reason,
        )

    def _log_halt(self, reason: str | None) -> None:
        if not reason or reason == self._halt_logged:
            return
        self._halt_logged = reason
        self.journal.write("halt", motivo=reason)
        self._event("halt", motivo=reason)
        log_event(self.logger, logging.ERROR, "agente travado para novas entradas", motivo=reason)
        self.notifier.send(f"{self.agent}: travado ({reason}). Posições seguem com stop.")

    def _entries_disabled(self) -> bool:
        if self.llm_dir is None:
            return False
        control = read_control(self.llm_dir.parent)
        if "enabled" in control:
            return not bool(control["enabled"])
        return not self.analyst_enabled

    def _apply_live_params(self) -> None:
        if self.llm_dir is None or not self.param_bounds:
            return
        params = read_control(self.llm_dir.parent).get("params") or {}
        if params:
            apply_params(self.strategies, params, self.param_bounds)

    def _remember_bar(self, bar: Bar) -> None:
        self.recent_bars.append(bar)
        if len(self.recent_bars) > 240:
            self.recent_bars = self.recent_bars[-240:]
        if self.llm_dir is None:
            return
        path = self.llm_dir.parent / "recent-bars.json"
        payload = [
            {
                "symbol": item.symbol,
                "ts": item.ts.isoformat(),
                "open": item.open,
                "high": item.high,
                "low": item.low,
                "close": item.close,
                "volume": item.volume,
                "timeframe": item.timeframe,
            }
            for item in self.recent_bars
        ]
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        temporary.replace(path)

    def _note_volume(self, bar: Bar) -> None:
        history = self._volumes.setdefault(bar.symbol, [])
        history.append(bar.volume)
        if len(history) > 21:
            del history[:-21]
        baseline = history[:-1]
        if len(baseline) < 5:
            return
        average = sum(baseline) / len(baseline)
        if average > 0 and bar.volume >= average * self.volume_spike_multiple:
            self._event("volume_spike", symbol=bar.symbol, volume=bar.volume, media=round(average, 4))

    def _event(self, kind: str, **fields: object) -> None:
        if self.llm_dir is None:
            return
        write_event(self.llm_dir.parent, kind, agent=self.agent, **fields)

    def _drain_llm(self, bar: Bar) -> None:
        if self.llm_dir is None:
            return
        inbox = self.llm_dir / "inbox"
        if not inbox.exists():
            return
        for path in sorted(inbox.glob("*.json")):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            key = str(payload.get("idempotency_key") or path.stem)
            if key in self.llm_done:
                path.unlink(missing_ok=True)
                continue
            if key in self.seen or any(item.client_order_id == key for item in self.llm_pending.values()):
                if key in self.seen:
                    write_result(self.llm_dir.parent, key, "preenchida", "ordem já passou pelo risco")
                    path.unlink(missing_ok=True)
                continue
            signal = signal_from_order(payload, bar.ts)
            self.journal.write(
                "llm_decision",
                source="llm",
                idempotency_key=key,
                symbol=signal.symbol,
                side=signal.side,
                stop=signal.stop_price,
                rationale=signal.rationale,
            )
            before = len(self.journal.path.read_text(encoding="utf-8").splitlines()) if self.journal.path.exists() else 0
            self._handle_signal(signal, bar)
            queued = self.llm_pending.get(signal.symbol)
            if queued is not None and queued.client_order_id == key:
                write_result(self.llm_dir.parent, key, "na_fila", "na fila da próxima barra; o risco julga no fill")
                self._event("llm_order", symbol=signal.symbol, side=signal.side)
            elif signal.symbol in self.positions and self.positions[signal.symbol].client_order_id == key:
                write_result(self.llm_dir.parent, key, "preenchida", "preenchida pelo motor de risco")
                path.unlink(missing_ok=True)
            else:
                detail = "recusada pelo risco ou por conflito de fonte"
                lines = self.journal.path.read_text(encoding="utf-8").splitlines()
                for line in reversed(lines[before:]):
                    item = json.loads(line)
                    if item.get("event") == "reject" and item.get("symbol") == signal.symbol:
                        detail = str(item.get("reason") or detail)
                        break
                write_result(self.llm_dir.parent, key, "recusada", detail, payload)
                path.unlink(missing_ok=True)

    def _equity(self) -> float:
        return float(self.broker.equity())


def _null_logger(agent: str) -> logging.Logger:
    logger = logging.getLogger(f"daytrade.null.{agent}")
    if not logger.handlers:
        logger.addHandler(logging.NullHandler())
    logger.propagate = False
    return logger


def _position_dict(position: Position) -> dict[str, object]:
    payload = asdict(position)
    payload["opened_at"] = position.opened_at.isoformat()
    if position.max_hold_until is not None:
        payload["max_hold_until"] = position.max_hold_until.isoformat()
    return payload


def _position_from(raw: dict) -> Position:
    opened = datetime.fromisoformat(raw["opened_at"])
    if opened.tzinfo is None:
        opened = opened.replace(tzinfo=timezone.utc)
    return Position(
        symbol=raw["symbol"],
        qty=float(raw["qty"]),
        avg_price=float(raw["avg_price"]),
        stop_price=float(raw["stop_price"]),
        opened_at=opened,
        strategy=raw["strategy"],
        entry_reason=raw["entry_reason"],
        entry_fee=float(raw["entry_fee"]),
        contract=raw["contract"],
        client_order_id=raw["client_order_id"],
        target_price=None if raw.get("target_price") is None else float(raw["target_price"]),
        source=str(raw.get("source") or "python"),
        max_hold_until=_parse_optional_time(raw.get("max_hold_until")),
    )


def _parse_optional_time(value: object) -> datetime | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(str(value))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed
