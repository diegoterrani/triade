"""Feed de barras. Replay não fala com corretora. O feed público da Binance fica no agente de cripto."""

from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path

from daytrade.common.models import Bar


def load_bars_csv(path: Path) -> list[Bar]:
    bars: list[Bar] = []
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            ts = datetime.fromisoformat(row["ts"])
            funding_raw = (row.get("funding_rate") or "").strip()
            funding = float(funding_raw) if funding_raw else None
            bars.append(
                Bar(
                    symbol=row["symbol"],
                    ts=ts,
                    open=float(row["open"]),
                    high=float(row["high"]),
                    low=float(row["low"]),
                    close=float(row["close"]),
                    volume=float(row["volume"]),
                    timeframe=row["timeframe"],
                    funding_rate=funding,
                )
            )
    bars.sort(key=lambda bar: (bar.ts, bar.symbol))
    return bars


class ReplayFeed:
    """Entrega barras já gravadas. `exhausted` encerra o paper sem esperar pregão."""

    def __init__(self, bars: list[Bar], max_bars: int | None = None) -> None:
        self.bars = list(bars)
        self.max_bars = max_bars
        self.index = 0
        self.exhausted = False
        self.idle_seconds = 0.0

    def poll(self) -> Bar | None:
        if self.max_bars is not None and self.index >= self.max_bars:
            self.exhausted = True
            return None
        if self.index >= len(self.bars):
            self.exhausted = True
            return None
        bar = self.bars[self.index]
        self.index += 1
        return bar

    def reconnect(self) -> bool:
        return True
