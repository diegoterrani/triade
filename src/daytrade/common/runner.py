"""Loop de paper e live. Backtest não passa por aqui: ele não dorme nem reconecta."""

from __future__ import annotations

import signal
import time
from collections.abc import Callable

from daytrade.common.errors import Disconnect
from daytrade.common.execution import ExecutionEngine

Sleeper = Callable[[float], None]


def run_loop(feed: object, engine: ExecutionEngine, sleeper: Sleeper = time.sleep) -> ExecutionEngine:
    def _on_term(signum, _frame):
        raise KeyboardInterrupt(signum)

    installed: list[tuple[signal.Signals, signal.Handlers]] = []
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            installed.append((sig, signal.signal(sig, _on_term)))
        except (ValueError, OSError):
            continue
    try:
        while True:
            kill_reason = engine.kill.tripped() if engine.kill is not None else None
            if kill_reason:
                engine.flatten_all(f"kill switch: {kill_reason}")
                engine.journal.write("kill", motivo=kill_reason)
                engine.notifier.send(f"{engine.agent}: encerrado pelo kill switch")
                engine.persist()
                break
            try:
                bar = feed.poll()
            except Disconnect as exc:
                engine.on_disconnect(str(exc))
                engine.persist()
                if not feed.reconnect():
                    engine.flatten_all("desconexão sem reconexão")
                    engine.journal.write("halt", motivo="desconexão sem reconexão")
                    engine.persist()
                    break
                engine.reconcile_and_adopt()
                engine.persist()
                continue
            if bar is None:
                if getattr(feed, "exhausted", False):
                    break
                sleeper(float(getattr(feed, "idle_seconds", 1.0)))
                continue
            status = engine.process_bar(bar)
            engine.persist()
            if status == "kill":
                break
    except KeyboardInterrupt:
        engine.journal.write("interrupt", motivo="interrupção do processo; zerando")
        engine.notifier.send(f"{engine.agent}: interrompido. Zerando.")
    finally:
        for sig, previous in installed:
            signal.signal(sig, previous)
    engine.flatten_all("encerramento do processo", ts=engine.last_bar_ts)
    engine.persist()
    return engine
