"""Ponte MT5 para o Python do Windows dentro do Wine.

Não importa o pacote daytrade: o Wine só precisa da biblioteca padrão e do
MetaTrader5. Escuta exclusivamente em 127.0.0.1. Um terminal, um prefixo, uma porta.

    wine C:\\Python312\\python.exe -u mt5_bridge_server.py --host 127.0.0.1 --port 18861
"""

from __future__ import annotations

import argparse
import json
import socket
import sys
import threading
from typing import Callable

HOST = "127.0.0.1"
MAX_LINE = 2_000_000

# Valores públicos do terminal. O módulo real substitui isto no ping.
CONSTANTS = {
    "POSITION_TYPE_BUY": 0,
    "TRADE_RETCODE_DONE": 10009,
    "TRADE_ACTION_DEAL": 1,
    "TRADE_ACTION_SLTP": 6,
    "TRADE_ACTION_REMOVE": 8,
    "ORDER_TYPE_BUY": 0,
    "ORDER_TYPE_SELL": 1,
    "ORDER_TIME_GTC": 0,
    "ORDER_FILLING_FOK": 0,
    "ORDER_FILLING_IOC": 1,
    "ORDER_FILLING_RETURN": 2,
    "TIMEFRAME_M1": 1,
    "TIMEFRAME_M5": 5,
    "TIMEFRAME_M15": 15,
    "TIMEFRAME_H1": 16385,
}


def assert_loopback(host: str) -> str:
    if host != HOST:
        raise SystemExit("a ponte só escuta em 127.0.0.1")
    return host


def serve(
    host: str,
    port: int,
    backend: object,
    *,
    stop: threading.Event | None = None,
    ready: threading.Event | None = None,
) -> None:
    assert_loopback(host)
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind((host, int(port)))
    sock.listen(1)
    sock.settimeout(0.2)
    if ready is not None:
        ready.set()
    try:
        while stop is None or not stop.is_set():
            try:
                conn, addr = sock.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            if addr[0] != HOST:
                conn.close()
                continue
            _session(conn, backend)
    finally:
        sock.close()


def dispatch(request: dict, backend: object) -> dict:
    method = str(request.get("method") or "")
    params = request.get("params") or {}
    if not isinstance(params, dict):
        return _err("params inválidos")
    handler = HANDLERS.get(method)
    if handler is None:
        return _err(f"método desconhecido: {method}")
    try:
        return {"ok": True, "result": handler(backend, params)}
    except Exception as exc:  # o terminal quebrou; o cliente trata como desconexão
        return _err(f"{type(exc).__name__}: {exc}")


def _ping(backend: object, _params: dict) -> dict:
    return {"pong": True, "initialized": bool(getattr(backend, "initialized", False)), "constants": _constants(backend)}


def _initialize(backend: object, params: dict) -> bool:
    kwargs: dict[str, object] = {}
    path = params.get("path") or ""
    if path:
        kwargs["path"] = path
    login = params.get("login")
    if login:
        kwargs["login"] = int(login)
        kwargs["password"] = params.get("password") or ""
        kwargs["server"] = params.get("server") or ""
    ok = bool(backend.initialize(**kwargs))
    backend.initialized = ok
    return ok


def _shutdown(backend: object, _params: dict) -> bool:
    backend.shutdown()
    backend.initialized = False
    return True


def _last_error(backend: object, _params: dict) -> list:
    return _plain(backend.last_error())


def _account_info(backend: object, _params: dict) -> dict | None:
    return _plain(backend.account_info())


def _positions_get(backend: object, params: dict) -> list:
    symbol = params.get("symbol")
    rows = backend.positions_get(symbol=symbol) if symbol else backend.positions_get()
    return _plain(rows) or []


def _orders_get(backend: object, _params: dict) -> list:
    return _plain(backend.orders_get()) or []


def _symbol_info(backend: object, params: dict) -> dict | None:
    return _plain(backend.symbol_info(params["symbol"]))


def _symbol_select(backend: object, params: dict) -> bool:
    return bool(backend.symbol_select(params["symbol"], bool(params.get("enable", True))))


def _symbol_info_tick(backend: object, params: dict) -> dict | None:
    return _plain(backend.symbol_info_tick(params["symbol"]))


def _order_send(backend: object, params: dict) -> dict | None:
    return _plain(backend.order_send(params["request"]))


def _copy_rates(backend: object, params: dict) -> list | None:
    rates = backend.copy_rates_from_pos(
        params["symbol"],
        int(params["timeframe"]),
        int(params["start"]),
        int(params["count"]),
    )
    return _plain(rates)


HANDLERS: dict[str, Callable[[object, dict], object]] = {
    "ping": _ping,
    "initialize": _initialize,
    "shutdown": _shutdown,
    "last_error": _last_error,
    "account_info": _account_info,
    "positions_get": _positions_get,
    "orders_get": _orders_get,
    "symbol_info": _symbol_info,
    "symbol_select": _symbol_select,
    "symbol_info_tick": _symbol_info_tick,
    "order_send": _order_send,
    "copy_rates_from_pos": _copy_rates,
}


def _constants(backend: object) -> dict[str, int]:
    values = {}
    for name, fallback in CONSTANTS.items():
        raw = getattr(backend, name, fallback)
        values[name] = int(raw)
    return values


def _plain(value: object) -> object:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, (bytes, bytearray)):
        return value.decode("utf-8", "replace")
    names = getattr(getattr(value, "dtype", None), "names", None)
    if names:
        shape = getattr(value, "shape", None)
        if shape == ():
            return {name: _plain(value[name]) for name in names}
        return [_plain(row) for row in value]
    if isinstance(value, dict):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    if hasattr(value, "_asdict"):
        return {key: _plain(item) for key, item in value._asdict().items()}
    fields = {key: _plain(item) for key, item in vars(value).items() if not str(key).startswith("_")}
    return fields or str(value)


def _err(message: str) -> dict:
    return {"ok": False, "error": message}


def _session(conn: socket.socket, backend: object) -> None:
    buf = b""
    try:
        while True:
            while b"\n" not in buf:
                if len(buf) > MAX_LINE:
                    conn.sendall(b'{"ok": false, "error": "pedido grande demais"}\n')
                    return
                chunk = conn.recv(65536)
                if not chunk:
                    return
                buf += chunk
            line, buf = buf.split(b"\n", 1)
            if not line.strip():
                continue
            try:
                request = json.loads(line)
            except json.JSONDecodeError:
                conn.sendall(b'{"ok": false, "error": "json invalido"}\n')
                continue
            if not isinstance(request, dict):
                conn.sendall(b'{"ok": false, "error": "pedido invalido"}\n')
                continue
            print(f"mt5bridge {request.get('method')}", flush=True)
            payload = dispatch(request, backend)
            payload["id"] = request.get("id")
            conn.sendall(json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8") + b"\n")
    except OSError as exc:
        print(f"mt5bridge conexao encerrada: {exc}", flush=True)
    finally:
        try:
            conn.close()
        except OSError:
            pass


def _load_backend():
    import MetaTrader5 as mt5

    mt5.initialized = False
    return mt5


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Ponte local do MetaTrader 5.")
    parser.add_argument("--host", default=HOST)
    parser.add_argument("--port", type=int, required=True)
    args = parser.parse_args(argv)
    try:
        assert_loopback(args.host)
    except SystemExit as exc:
        print(exc, file=sys.stderr)
        return 2
    if not 1 <= args.port <= 65535:
        print("porta inválida", file=sys.stderr)
        return 2
    backend = _load_backend()
    print(f"mt5bridge escutando {args.host}:{args.port}", flush=True)
    serve(args.host, args.port, backend)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
