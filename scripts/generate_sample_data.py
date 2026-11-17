"""Gera as séries sintéticas de B3 e NASDAQ. Não tenta imitar um pregão real."""

from __future__ import annotations

import csv
import random
from datetime import datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from daytrade.b3.calendar import session_checker as b3_sessions
from daytrade.common.prices import nearest_tick
from daytrade.nasdaq.calendar import session_checker as nyse_sessions

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "sample"


def sessions(start, count, is_session):
    day = start
    found = 0
    while found < count:
        if is_session(day):
            yield day
            found += 1
        day += timedelta(days=1)


def clock_range(open_hour: int, open_minute: int, close_hour: int, close_minute: int, step: int):
    cursor = datetime(2000, 1, 1, open_hour, open_minute)
    end = datetime(2000, 1, 1, close_hour, close_minute)
    while cursor <= end:
        yield cursor.time()
        cursor += timedelta(minutes=step)


def write_market(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["symbol", "ts", "open", "high", "low", "close", "volume", "timeframe", "funding_rate"],
        )
        writer.writeheader()
        writer.writerows(rows)


def build_series(
    *,
    symbol: str,
    tz: ZoneInfo,
    days,
    opens: list[time],
    start_price: float,
    tick: float,
    vol: float,
    rng: random.Random,
    timeframe: str,
) -> tuple[list[dict], float]:
    price = start_price
    rows = []
    for day in days:
        for clock in opens:
            ts = datetime(day.year, day.month, day.day, clock.hour, clock.minute, tzinfo=tz)
            shock = rng.gauss(0, vol)
            close = nearest_tick(price * (1 + shock), tick)
            high = nearest_tick(max(price, close) + abs(rng.gauss(0, vol * price * 0.5)), tick)
            low = nearest_tick(min(price, close) - abs(rng.gauss(0, vol * price * 0.5)), tick)
            open_ = nearest_tick(price, tick)
            high = max(high, open_, close)
            low = min(low, open_, close)
            rows.append(
                {
                    "symbol": symbol,
                    "ts": ts.isoformat(),
                    "open": f"{open_:.10g}",
                    "high": f"{high:.10g}",
                    "low": f"{low:.10g}",
                    "close": f"{close:.10g}",
                    "volume": f"{rng.uniform(500, 5000):.0f}",
                    "timeframe": timeframe,
                    "funding_rate": "",
                }
            )
            price = close
    return rows, price


def main() -> None:
    rng = random.Random(20261117)
    b3_days = list(sessions(datetime(2024, 8, 1).date(), 40, b3_sessions()))
    b3_clocks = list(clock_range(9, 0, 18, 20, 5))
    win, _ = build_series(
        symbol="WIN",
        tz=ZoneInfo("America/Sao_Paulo"),
        days=b3_days,
        opens=b3_clocks,
        start_price=128000,
        tick=5,
        vol=0.0008,
        rng=rng,
        timeframe="5m",
    )
    wdo, _ = build_series(
        symbol="WDO",
        tz=ZoneInfo("America/Sao_Paulo"),
        days=b3_days,
        opens=b3_clocks,
        start_price=5450,
        tick=0.5,
        vol=0.00045,
        rng=rng,
        timeframe="5m",
    )
    write_market(OUT / "b3_win_wdo_5m.csv", win + wdo)

    ny_days = list(sessions(datetime(2024, 9, 3).date(), 40, nyse_sessions()))
    ny_clocks = list(clock_range(9, 30, 15, 55, 5))
    ustec, _ = build_series(
        symbol="USTEC",
        tz=ZoneInfo("America/New_York"),
        days=ny_days,
        opens=ny_clocks,
        start_price=19500,
        tick=0.1,
        vol=0.0007,
        rng=rng,
        timeframe="5m",
    )
    write_market(OUT / "nasdaq_ustec_5m.csv", ustec)
    print(f"B3: {len(win) + len(wdo)} barras em {OUT / 'b3_win_wdo_5m.csv'}")
    print(f"NASDAQ: {len(ustec)} barras em {OUT / 'nasdaq_ustec_5m.csv'}")


if __name__ == "__main__":
    main()
