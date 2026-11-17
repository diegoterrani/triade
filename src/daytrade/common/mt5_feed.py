"""Barras do MetaTrader 5. A posição 0 é o candle ainda aberto; lemos a partir da 1.

`time_offset_hours` corrige corretora que grava a hora local como se fosse UTC.
O padrão é 0. Confira um candle conhecido antes de operar.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from daytrade.common.errors import Disconnect
from daytrade.common.models import Bar
from daytrade.common.symbols import SymbolRouter

_TIMEFRAMES = {"1m": "TIMEFRAME_M1", "5m": "TIMEFRAME_M5", "15m": "TIMEFRAME_M15", "1h": "TIMEFRAME_H1"}


class MT5BarFeed:
    def __init__(
        self,
        broker,
        router: SymbolRouter,
        symbols: list[str],
        timeframe: str,
        *,
        time_offset_hours: float = 0.0,
        max_bars: int | None = None,
    ) -> None:
        if timeframe not in _TIMEFRAMES:
            raise ValueError(f"timeframe não suportado no MT5: {timeframe}")
        self.broker = broker
        self.router = router
        self.symbols = symbols
        self.timeframe = timeframe
        self.offset = timedelta(hours=time_offset_hours)
        self.max_bars = max_bars
        self.idle_seconds = 5.0
        self.exhausted = False
        self.yielded = 0
        self.seen: set[tuple[str, datetime]] = set()
        self.queue: list[Bar] = []

    def poll(self) -> Bar | None:
        if self.max_bars is not None and self.yielded >= self.max_bars:
            self.exhausted = True
            return None
        if not self.queue:
            self._pull()
        if not self.queue:
            return None
        self.yielded += 1
        return self.queue.pop(0)

    def reconnect(self) -> bool:
        try:
            self.broker.connect()
            return True
        except (Disconnect, Exception):
            return False

    def _pull(self) -> None:
        mt5 = self.broker._mt5
        if mt5 is None:
            self.broker.connect()
            mt5 = self.broker._mt5
        timeframe = getattr(mt5, _TIMEFRAMES[self.timeframe])
        now = datetime.now(timezone.utc)
        fresh: list[Bar] = []
        for internal in self.symbols:
            venue = self.router.venue(internal, now)
            rates = mt5.copy_rates_from_pos(venue, timeframe, 1, 3)
            if rates is None:
                raise Disconnect(f"copy_rates falhou para {venue}: {mt5.last_error()}")
            for rate in rates:
                ts = datetime.fromtimestamp(int(rate["time"]), tz=timezone.utc) + self.offset
                key = (internal, ts)
                if key in self.seen:
                    continue
                self.seen.add(key)
                fresh.append(
                    Bar(
                        symbol=internal,
                        ts=ts,
                        open=float(rate["open"]),
                        high=float(rate["high"]),
                        low=float(rate["low"]),
                        close=float(rate["close"]),
                        volume=float(rate["tick_volume"]),
                        timeframe=self.timeframe,
                    )
                )
        fresh.sort(key=lambda bar: (bar.ts, bar.symbol))
        self.queue.extend(fresh)
