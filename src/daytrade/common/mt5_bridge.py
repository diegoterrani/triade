"""Cliente da ponte MT5. O agente Linux não importa MetaTrader5.

O processo do outro lado roda dentro do Wine, no mesmo prefixo do terminal, e só
escuta em 127.0.0.1. Cada chamada tem prazo. Prazo estourado ou conexão caída
vira Disconnect: o loop descarta o sinal pendente, não abre mão nova e só
reconcilia depois que a ponte voltar.
"""

from __future__ import annotations

import json
import socket
import time
from types import SimpleNamespace

from daytrade.common.errors import Disconnect, SafetyError

LOOPBACK = "127.0.0.1"


def assert_loopback(host: str) -> str:
    if host != LOOPBACK:
        raise SafetyError(
            "a ponte MT5 só aceita 127.0.0.1. Não publique essa porta e não use outro endereço."
        )
    return host


class BridgeClient:
    """Superfície usada pelo MT5Broker. Os métodos espelham o módulo MetaTrader5."""

    def __init__(
        self,
        host: str,
        port: int,
        *,
        timeout: float = 5.0,
        heartbeat: float = 5.0,
    ) -> None:
        self.host = assert_loopback(host)
        self.port = int(port)
        if not 1 <= self.port <= 65535:
            raise SafetyError(f"porta da ponte inválida: {port}")
        if timeout <= 0 or heartbeat <= 0:
            raise SafetyError("timeout e heartbeat da ponte têm de ser positivos")
        self.timeout = float(timeout)
        self.heartbeat = float(heartbeat)
        self.sock: socket.socket | None = None
        self.alive = False
        self._buf = b""
        self._seq = 0
        self._last_ok = 0.0

    def connect(self) -> None:
        self.close()
        try:
            sock = socket.create_connection((self.host, self.port), timeout=self.timeout)
        except OSError as exc:
            raise Disconnect(f"ponte MT5 inacessível em {self.host}:{self.port}: {exc}") from exc
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self.sock = sock
        self.alive = True
        self._buf = b""
        pong = self.call("ping", {}, timeout=self.timeout)
        if not isinstance(pong, dict) or not pong.get("pong"):
            self._fail("ponte MT5 respondeu um ping inválido")
        constants = pong.get("constants") or {}
        if isinstance(constants, dict):
            for name, value in constants.items():
                setattr(self, str(name), int(value))

    def close(self) -> None:
        self.alive = False
        sock = self.sock
        self.sock = None
        self._buf = b""
        if sock is not None:
            try:
                sock.close()
            except OSError:
                pass

    def heartbeat(self) -> None:
        if not self.alive or self.sock is None:
            raise Disconnect("ponte MT5 caída")
        if time.monotonic() - self._last_ok <= self.heartbeat:
            return
        self.call("ping", {})

    def initialize(self, **kwargs: object) -> bool:
        payload = {
            "path": kwargs.get("path") or "",
            "login": kwargs.get("login"),
            "password": kwargs.get("password") or "",
            "server": kwargs.get("server") or "",
        }
        return bool(self.call("initialize", payload, timeout=max(self.timeout, 20.0)))

    def shutdown(self) -> None:
        if self.alive:
            try:
                self.call("shutdown", {}, timeout=self.timeout)
            except Disconnect:
                pass
        self.close()

    def last_error(self) -> object:
        return self.call("last_error", {})

    def account_info(self) -> SimpleNamespace | None:
        return _namespace(self.call("account_info", {}))

    def positions_get(self, symbol: str | None = None) -> list[SimpleNamespace]:
        params = {} if symbol is None else {"symbol": symbol}
        result = self.call("positions_get", params)
        return [_namespace(item) for item in result or []]

    def orders_get(self) -> list[SimpleNamespace]:
        result = self.call("orders_get", {})
        return [_namespace(item) for item in result or []]

    def symbol_info(self, symbol: str) -> SimpleNamespace | None:
        return _namespace(self.call("symbol_info", {"symbol": symbol}))

    def symbol_select(self, symbol: str, enable: bool = True) -> bool:
        return bool(self.call("symbol_select", {"symbol": symbol, "enable": bool(enable)}))

    def symbol_info_tick(self, symbol: str) -> SimpleNamespace | None:
        return _namespace(self.call("symbol_info_tick", {"symbol": symbol}))

    def order_send(self, request: dict) -> SimpleNamespace | None:
        return _namespace(self.call("order_send", {"request": request}))

    def copy_rates_from_pos(self, symbol: str, timeframe: int, start: int, count: int) -> list[dict] | None:
        result = self.call(
            "copy_rates_from_pos",
            {"symbol": symbol, "timeframe": int(timeframe), "start": int(start), "count": int(count)},
        )
        if result is None:
            return None
        return [dict(item) for item in result]

    def call(self, method: str, params: dict, timeout: float | None = None) -> object:
        if self.sock is None or not self.alive:
            raise Disconnect(f"ponte MT5 sem conexão ao chamar {method}")
        self._seq += 1
        ident = self._seq
        raw = json.dumps({"id": ident, "method": method, "params": params}, ensure_ascii=False) + "\n"
        deadline = time.monotonic() + float(self.timeout if timeout is None else timeout)
        try:
            self._send(raw.encode("utf-8"), deadline)
            line = self._read_line(deadline)
        except Disconnect:
            raise
        except (TimeoutError, socket.timeout, OSError) as exc:
            self._fail(f"ponte MT5 sem resposta em {method}: {exc}")
        try:
            payload = json.loads(line)
        except json.JSONDecodeError as exc:
            self._fail(f"ponte MT5 devolveu JSON inválido em {method}")
        if payload.get("id") != ident:
            self._fail(f"ponte MT5 devolveu id inesperado em {method}")
        if not payload.get("ok"):
            self._fail(str(payload.get("error") or f"ponte MT5 falhou em {method}"))
        self._last_ok = time.monotonic()
        return payload.get("result")

    def _send(self, data: bytes, deadline: float) -> None:
        view = memoryview(data)
        while view:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                self._fail("prazo esgotado ao enviar para a ponte MT5")
            assert self.sock is not None
            self.sock.settimeout(remaining)
            try:
                sent = self.sock.send(view)
            except (TimeoutError, socket.timeout, OSError) as exc:
                self._fail(f"ponte MT5 sem resposta no envio: {exc}")
            view = view[sent:]

    def _read_line(self, deadline: float) -> str:
        while b"\n" not in self._buf:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                self._fail("prazo esgotado aguardando a ponte MT5")
            if len(self._buf) > 2_000_000:
                self._fail("resposta da ponte MT5 passou do tamanho permitido")
            assert self.sock is not None
            self.sock.settimeout(remaining)
            try:
                chunk = self.sock.recv(65536)
            except (TimeoutError, socket.timeout, OSError) as exc:
                self._fail(f"ponte MT5 sem resposta na leitura: {exc}")
            if not chunk:
                self._fail("ponte MT5 fechou a conexão")
            self._buf += chunk
        line, self._buf = self._buf.split(b"\n", 1)
        return line.decode("utf-8")

    def _fail(self, message: str) -> None:
        self.close()
        raise Disconnect(message)


def _namespace(value: object) -> SimpleNamespace | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise Disconnect("ponte MT5 devolveu um objeto que não é um mapa")
    return SimpleNamespace(**value)
