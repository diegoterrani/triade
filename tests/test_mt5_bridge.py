"""Ponte MT5 com um servidor falso: prazo, queda e reconciliação."""

from __future__ import annotations

import importlib.util
import socket
import threading
import time
from datetime import timezone
from types import SimpleNamespace

import pytest

from daytrade.common.broker_paper import PaperBroker
from daytrade.common.config import load_config, project_root
from daytrade.common.errors import Disconnect, SafetyError
from daytrade.common.execution import ExecutionEngine
from daytrade.common.journal import Journal
from daytrade.common.models import Instrument
from daytrade.common.mt5_bridge import BridgeClient
from daytrade.common.mt5_broker import MT5Broker
from daytrade.common.risk import RiskLimits, RiskManager
from daytrade.common.runner import run_loop
from daytrade.common.symbols import IdentityRouter
from daytrade.mt5bridge.__main__ import main


def _server_module():
    path = project_root() / "scripts" / "linux" / "mt5_bridge_server.py"
    spec = importlib.util.spec_from_file_location("mt5_bridge_server_under_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeMT5:
    def __init__(self) -> None:
        self.initialized = False
        self.delay = 0.0
        self.equity = 5000.0

    def initialize(self, **_kwargs) -> bool:
        self.initialized = True
        return True

    def shutdown(self) -> None:
        self.initialized = False

    def last_error(self):
        return [1, "ok"]

    def account_info(self):
        if self.delay:
            time.sleep(self.delay)
        return SimpleNamespace(equity=self.equity)

    def positions_get(self, symbol=None):
        return []

    def orders_get(self):
        return []

    def symbol_info(self, symbol):
        return SimpleNamespace(volume_min=1, volume_step=1, trade_tick_size=5, trade_tick_value=1.0)

    def symbol_select(self, symbol, enable=True):
        return True

    def symbol_info_tick(self, symbol):
        return SimpleNamespace(bid=100.0, ask=101.0)

    def order_send(self, request):
        return SimpleNamespace(retcode=10009, comment="ok", price=101.0, volume=request.get("volume", 0))

    def copy_rates_from_pos(self, symbol, timeframe, start, count):
        return [{"time": 1_700_000_000, "open": 1, "high": 2, "low": 0.5, "close": 1.5, "tick_volume": 10}]


def _free_port() -> int:
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


@pytest.fixture
def running():
    module = _server_module()
    backend = FakeMT5()
    port = _free_port()
    stop = threading.Event()
    ready = threading.Event()
    thread = threading.Thread(
        target=module.serve,
        args=("127.0.0.1", port, backend),
        kwargs={"stop": stop, "ready": ready},
        daemon=True,
    )
    thread.start()
    assert ready.wait(2)
    yield port, backend
    stop.set()
    thread.join(2)


def _instrument() -> Instrument:
    return Instrument("WIN", "WIN", 5, 0.2, 1, 1, "BRL", max_qty=1)


def test_configs_keep_the_bridge_on_loopback_and_on_different_ports():
    b3 = load_config("configs/b3.yaml")["mt5"]
    nasdaq = load_config("configs/nasdaq.yaml")["mt5"]
    assert b3["transport"] == "bridge"
    assert nasdaq["transport"] == "bridge"
    assert b3["bridge_host"] == nasdaq["bridge_host"] == "127.0.0.1"
    assert b3["bridge_port"] != nasdaq["bridge_port"]


def test_non_loopback_is_refused():
    with pytest.raises(SafetyError, match="127.0.0.1"):
        BridgeClient("0.0.0.0", 18861)
    module = _server_module()
    with pytest.raises(SystemExit, match="127.0.0.1"):
        module.serve("0.0.0.0", 9, FakeMT5())


def test_broker_talks_to_the_fake_server_and_a_timeout_is_disconnect(running):
    port, backend = running
    broker = MT5Broker(
        terminal_path="",
        login="1",
        password="segredo",
        server="Servidor",
        magic=26011701,
        instruments={"WIN": _instrument()},
        router=IdentityRouter(),
        transport="bridge",
        bridge_host="127.0.0.1",
        bridge_port=port,
        bridge_timeout=0.2,
        bridge_heartbeat=0.05,
    )
    broker.connect()
    assert broker.equity() == 5000
    rates = broker._mt5.copy_rates_from_pos("WIN", broker._mt5.TIMEFRAME_M5, 1, 3)
    assert rates[0]["close"] == 1.5
    backend.delay = 0.6
    with pytest.raises(Disconnect, match="ponte"):
        broker.equity()
    with pytest.raises(Disconnect, match="caída"):
        broker.heartbeat()
    backend.delay = 0.0
    time.sleep(0.7)
    broker.connect()
    assert broker.equity() == 5000
    broker.shutdown()
    assert main(["check", "--host", "127.0.0.1", "--port", str(port), "--timeout", "1"]) == 0


def test_dropped_socket_is_disconnect():
    port = _free_port()
    ready = threading.Event()

    def once() -> None:
        sock = socket.socket()
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("127.0.0.1", port))
        sock.listen(1)
        ready.set()
        conn, _addr = sock.accept()
        buf = b""
        while b"\n" not in buf:
            buf += conn.recv(4096)
        conn.sendall(b'{"id": 1, "ok": true, "result": {"pong": true, "constants": {}}}\n')
        buf = b""
        while b"\n" not in buf:
            chunk = conn.recv(4096)
            if not chunk:
                break
            buf += chunk
        conn.close()
        sock.close()

    threading.Thread(target=once, daemon=True).start()
    assert ready.wait(2)
    client = BridgeClient("127.0.0.1", port, timeout=1, heartbeat=1)
    client.connect()
    with pytest.raises(Disconnect, match="fechou"):
        client.account_info()
    assert client.alive is False


def test_bridge_loss_during_the_bar_reconciles_and_does_not_reenter(tmp_path):
    class Feed:
        def __init__(self) -> None:
            self.idle_seconds = 0
            self.exhausted = False
            self.calls = 0

        def poll(self):
            self.calls += 1
            if self.calls == 1:
                raise Disconnect("ponte MT5 sem resposta")
            self.exhausted = True
            return None

        def reconnect(self) -> bool:
            return True

    instrument = _instrument()
    broker = PaperBroker({"WIN": instrument}, 5_000)
    engine = ExecutionEngine(
        agent="b3",
        broker=broker,
        risk=RiskManager(RiskLimits(0.01, 4, 0.02, 0.04), equity=5_000),
        instruments={"WIN": instrument},
        strategies={},
        journal=Journal(tmp_path / "journal.jsonl"),
        risk_tz=timezone.utc,
    )
    feed = Feed()
    run_loop(feed, engine, sleeper=lambda _seconds: None)
    text = (tmp_path / "journal.jsonl").read_text(encoding="utf-8")
    assert "disconnect" in text
    assert "ponte MT5 sem resposta" in text
    assert "reconcile" in text
    assert engine.pending == {}
    assert engine.positions == {}


def test_bridge_loss_without_reconnect_stops(tmp_path):
    class Feed:
        idle_seconds = 0
        exhausted = False

        def poll(self):
            raise Disconnect("ponte caída")

        def reconnect(self) -> bool:
            return False

    instrument = _instrument()
    engine = ExecutionEngine(
        agent="b3",
        broker=PaperBroker({"WIN": instrument}, 5_000),
        risk=RiskManager(RiskLimits(0.01, 4, 0.02, 0.04), equity=5_000),
        instruments={"WIN": instrument},
        strategies={},
        journal=Journal(tmp_path / "journal.jsonl"),
        risk_tz=timezone.utc,
    )
    run_loop(Feed(), engine, sleeper=lambda _seconds: None)
    text = (tmp_path / "journal.jsonl").read_text(encoding="utf-8")
    assert "desconexão sem reconexão" in text
