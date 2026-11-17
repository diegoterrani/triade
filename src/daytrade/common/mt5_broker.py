"""Cliente MetaTrader 5. Import tardio: em Linux o módulo não existe e o paper segue de pé.

A escolha do MT5, e não do cTrader, está no README do agente NASDAQ e vale também
para a B3: os dois agentes usam a mesma API, em processos e terminais diferentes.
"""

from __future__ import annotations

import time
from dataclasses import replace
from datetime import datetime, timezone

from daytrade.common.errors import Disconnect, SafetyError
from daytrade.common.models import Fill, Instrument, OrderRequest
from daytrade.common.mt5_bridge import BridgeClient
from daytrade.common.specs import assert_point_value, read_terminal_spec
from daytrade.common.symbols import SymbolRouter

# Códigos públicos do protocolo do terminal. O teste não precisa do pacote.
TRANSIENT_RETCODES = {10004, 10012, 10020, 10021, 10031}
INVALID_FILL_RETCODE = 10030
DONE_RETCODE = 10009


def should_retry(retcode: int) -> bool:
    return retcode in TRANSIENT_RETCODES


def build_order_request(
    *,
    venue_symbol: str,
    side: str,
    qty: float,
    price: float,
    stop: float | None,
    magic: int,
    client_order_id: str,
    deviation: int,
    reduce_only: bool,
) -> dict[str, object]:
    if not reduce_only and stop is None:
        raise SafetyError("ordem de entrada sem stop")
    return {
        "action": "DEAL",
        "symbol": venue_symbol,
        "volume": float(qty),
        "type": "BUY" if side == "buy" else "SELL",
        "price": float(price),
        "sl": float(stop or 0.0),
        "deviation": int(deviation),
        "magic": int(magic),
        "comment": client_order_id[:31],
        "type_time": "GTC",
        "type_filling": "IOC",
    }


class MT5Broker:
    def __init__(
        self,
        *,
        terminal_path: str,
        login: str,
        password: str,
        server: str,
        magic: int,
        instruments: dict[str, Instrument],
        router: SymbolRouter,
        deviation: int = 20,
        demo: bool = False,
        adopt_terminal_spec: bool = False,
        transport: str = "direct",
        bridge_host: str = "127.0.0.1",
        bridge_port: int = 18861,
        bridge_timeout: float = 5.0,
        bridge_heartbeat: float = 5.0,
    ) -> None:
        self.terminal_path = terminal_path
        self.login = login
        self.password = password
        self.server = server
        self.magic = magic
        self.instruments = instruments
        self.router = router
        self.deviation = deviation
        self.demo = demo
        self.adopt_terminal_spec = adopt_terminal_spec
        self.transport = transport
        self.bridge_host = bridge_host
        self.bridge_port = int(bridge_port)
        self.bridge_timeout = float(bridge_timeout)
        self.bridge_heartbeat = float(bridge_heartbeat)
        if self.transport not in ("direct", "bridge"):
            raise SafetyError("mt5.transport é direct ou bridge")
        self.last: dict[str, float] = {}
        self._mt5 = None

    def connect(self) -> None:
        self._mt5 = self._open_session()
        kwargs: dict[str, object] = {}
        if self.terminal_path:
            kwargs["path"] = self.terminal_path
        if self.login:
            kwargs["login"] = int(self.login)
            kwargs["password"] = self.password
            kwargs["server"] = self.server
        if not self._mt5.initialize(**kwargs):
            raise Disconnect(f"MT5 não inicializou: {self._mt5.last_error()}")
        self._check_specs()

    def heartbeat(self) -> None:
        if self.transport != "bridge":
            return
        if self._mt5 is None or not getattr(self._mt5, "alive", False):
            raise Disconnect("ponte MT5 caída")
        self._mt5.heartbeat()

    def _open_session(self):
        if self.transport == "direct":
            try:
                import MetaTrader5 as mt5
            except ImportError as exc:
                raise SafetyError(
                    "O pacote MetaTrader5 não está disponível neste Python. "
                    "No VPS Linux ele roda dentro do Wine, com mt5.transport: bridge. "
                    "No Windows nativo use mt5.transport: direct. "
                    "Backtest e paper com replay continuam sem o terminal."
                ) from exc
            return mt5
        if self._mt5 is not None and getattr(self._mt5, "alive", False):
            self._mt5.close()
        client = BridgeClient(
            self.bridge_host,
            self.bridge_port,
            timeout=self.bridge_timeout,
            heartbeat=self.bridge_heartbeat,
        )
        client.connect()
        return client

    def mark(self, symbol: str, price: float) -> None:
        self.last[symbol] = price

    def equity(self) -> float:
        self._require()
        info = self._mt5.account_info()
        if info is None:
            raise Disconnect(f"account_info falhou: {self._mt5.last_error()}")
        return float(info.equity)

    def positions(self) -> dict[str, float]:
        self._require()
        totals: dict[str, float] = {}
        for position in self._mt5.positions_get() or []:
            if int(position.magic) != self.magic:
                continue
            internal = self.router.internal(position.symbol)
            signed = float(position.volume) if int(position.type) == int(self._mt5.POSITION_TYPE_BUY) else -float(position.volume)
            totals[internal] = totals.get(internal, 0.0) + signed
        return {symbol: qty for symbol, qty in totals.items() if abs(qty) > 1e-12}

    def cancel_all(self) -> int:
        self._require()
        removed = 0
        for order in self._mt5.orders_get() or []:
            if int(order.magic) != self.magic:
                continue
            request = {"action": self._mt5.TRADE_ACTION_REMOVE, "order": int(order.ticket)}
            result = self._mt5.order_send(request)
            if result is not None and int(result.retcode) == int(self._mt5.TRADE_RETCODE_DONE):
                removed += 1
        return removed

    def submit(self, order: OrderRequest, ref_price: float) -> Fill:
        self._require()
        if not order.reduce_only and order.stop_price is None:
            raise SafetyError("ordem de entrada sem stop")
        venue = self.router.venue(order.symbol, order.ts)
        tick = self._mt5.symbol_info_tick(venue)
        if tick is None:
            raise Disconnect(f"sem cotação de {venue}")
        price = float(tick.ask if order.side == "buy" else tick.bid)
        request = build_order_request(
            venue_symbol=venue,
            side=order.side,
            qty=order.qty,
            price=price,
            stop=order.stop_price,
            magic=self.magic,
            client_order_id=order.client_order_id,
            deviation=self.deviation,
            reduce_only=order.reduce_only,
        )
        result = self._send(request)
        if result is None or int(result.retcode) != int(self._mt5.TRADE_RETCODE_DONE):
            comment = "" if result is None else str(result.comment)
            code = None if result is None else int(result.retcode)
            raise SafetyError(f"MT5 recusou a ordem {order.client_order_id}: {code} {comment}")
        fill_price = float(result.price or price)
        instrument = self.instruments[order.symbol]
        self.last[order.symbol] = fill_price
        return Fill(
            client_order_id=order.client_order_id,
            symbol=order.symbol,
            side=order.side,
            qty=float(result.volume or order.qty),
            price=fill_price,
            fee=instrument.fee(order.qty, fill_price),
            ts=order.ts,
            reduce_only=order.reduce_only,
        )

    def attach_stop(self, symbol: str, qty: float, stop: float) -> None:
        self._require()
        venue = self.router.venue(symbol, datetime.now(timezone.utc))
        for position in self._mt5.positions_get(symbol=venue) or []:
            if int(position.magic) != self.magic:
                continue
            request = {
                "action": self._mt5.TRADE_ACTION_SLTP,
                "symbol": venue,
                "position": int(position.ticket),
                "sl": float(stop),
                "tp": float(position.tp),
                "magic": self.magic,
            }
            result = self._mt5.order_send(request)
            if result is None or int(result.retcode) != int(self._mt5.TRADE_RETCODE_DONE):
                raise SafetyError(f"não foi possível gravar o stop de emergência em {venue}")
            return
        raise SafetyError(f"não achei posição de magic {self.magic} em {venue} para gravar o stop")

    def shutdown(self) -> None:
        if self._mt5 is None:
            return
        try:
            self._mt5.shutdown()
        except Disconnect:
            pass
        self._mt5 = None

    def _check_specs(self) -> None:
        now = datetime.now(timezone.utc)
        for internal, instrument in self.instruments.items():
            venue = self.router.venue(internal, now)
            info = self._mt5.symbol_info(venue)
            if info is None:
                raise SafetyError(
                    f"Símbolo {venue} não existe neste terminal. "
                    "Confira o Market Watch e o symbol_suffix do config."
                )
            if not self._mt5.symbol_select(venue, True):
                raise SafetyError(f"não consegui selecionar {venue} no Market Watch")
            if self.adopt_terminal_spec:
                spec = read_terminal_spec(
                    venue,
                    volume_min=getattr(info, "volume_min", None),
                    volume_step=getattr(info, "volume_step", None),
                    tick_size=getattr(info, "trade_tick_size", None),
                    tick_value=getattr(info, "trade_tick_value", None),
                )
                self.instruments[internal] = replace(
                    instrument,
                    min_qty=spec["min_qty"],
                    lot_step=spec["lot_step"],
                    tick_size=spec["tick_size"],
                    point_value=spec["point_value"],
                    max_qty=spec["min_qty"],
                )
                continue
            assert_point_value(
                symbol=venue,
                config_point_value=instrument.point_value,
                broker_tick_value=float(info.trade_tick_value),
                broker_tick_size=float(info.trade_tick_size),
            )

    def _send(self, request: dict):
        mt5 = self._mt5
        fillings = [
            mt5.ORDER_FILLING_IOC,
            mt5.ORDER_FILLING_FOK,
            mt5.ORDER_FILLING_RETURN,
        ]
        last = None
        side_name = request["type"]
        for filling in fillings:
            request["type_filling"] = filling
            request["action"] = mt5.TRADE_ACTION_DEAL
            request["type"] = mt5.ORDER_TYPE_BUY if side_name == "BUY" else mt5.ORDER_TYPE_SELL
            request["type_time"] = mt5.ORDER_TIME_GTC
            for attempt in range(3):
                last = mt5.order_send(request)
                if last is not None and int(last.retcode) == int(mt5.TRADE_RETCODE_DONE):
                    return last
                code = None if last is None else int(last.retcode)
                if code is not None and should_retry(code):
                    time.sleep(0.4 * (attempt + 1))
                    continue
                break
            if last is not None and int(last.retcode) == INVALID_FILL_RETCODE:
                continue
            break
        return last

    def _require(self) -> None:
        if self._mt5 is None:
            self.connect()
            return
        if self.transport == "bridge" and not getattr(self._mt5, "alive", False):
            raise Disconnect("ponte MT5 caída")


def mt5_connection_kwargs(mt5_cfg: dict) -> dict[str, object]:
    return {
        "transport": str(mt5_cfg.get("transport", "direct")),
        "bridge_host": str(mt5_cfg.get("bridge_host", "127.0.0.1")),
        "bridge_port": int(mt5_cfg.get("bridge_port", 18861)),
        "bridge_timeout": float(mt5_cfg.get("bridge_timeout_seconds", 5)),
        "bridge_heartbeat": float(mt5_cfg.get("bridge_heartbeat_seconds", 5)),
    }
