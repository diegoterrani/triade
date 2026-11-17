"""Baixa klines públicos de USD-M e o funding. Não usa chave.

O REST de fapi.binance.com devolve HTTP 451 em algumas redes. Nesse caso o
script lê o mesmo dado público em data.binance.vision (arquivos diários e
mensais). O host de ordem não muda: isto aqui é só histórico.
"""

from __future__ import annotations

import csv
import io
import json
import zipfile
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import requests

from daytrade.common.errors import SafetyError
from daytrade.crypto.binance_api import attach_funding, base_url, download_funding, download_klines, kline_to_bar

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "sample" / "binance_btcusdt_ethusdt_15m.csv"
META = ROOT / "data" / "sample" / "binance_filters.json"
VISION = "https://data.binance.vision/data/futures/um"


def _next_month(moment: datetime) -> datetime:
    if moment.month == 12:
        return moment.replace(year=moment.year + 1, month=1, day=1)
    return moment.replace(month=moment.month + 1, day=1)


def _months(start: datetime, end: datetime):
    cursor = start.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    while cursor < end:
        nxt = _next_month(cursor)
        yield cursor, nxt
        cursor = nxt


def _zip_text(session: requests.Session, url: str) -> str | None:
    response = session.get(url, timeout=60)
    if response.status_code == 404:
        return None
    if response.status_code >= 400:
        raise SafetyError(f"HTTP {response.status_code} em {url}")
    archive = zipfile.ZipFile(io.BytesIO(response.content))
    name = next(item for item in archive.namelist() if item.endswith(".csv"))
    return archive.read(name).decode()


def _data_rows(text: str) -> list[list[str]]:
    rows = []
    for row in csv.reader(io.StringIO(text)):
        if row and row[0][:1].isdigit():
            rows.append(row)
    return rows


def _vision(symbol: str, start: datetime, end: datetime, session: requests.Session):
    klines: list[list] = []
    funding: list[tuple[datetime, float]] = []
    price_text: list[str] = []
    for month, nxt in _months(start, end):
        tag = month.strftime("%Y-%m")
        complete = nxt <= end
        ktext = (
            _zip_text(session, f"{VISION}/monthly/klines/{symbol}/15m/{symbol}-15m-{tag}.zip") if complete else None
        )
        ftext = (
            _zip_text(session, f"{VISION}/monthly/fundingRate/{symbol}/{symbol}-fundingRate-{tag}.zip")
            if complete
            else None
        )
        chunks: list[tuple[str | None, str | None]] = []
        if ktext:
            chunks.append((ktext, ftext))
        else:
            day = max(month, start).date()
            last = min(nxt, end).date()
            while day <= last and datetime(day.year, day.month, day.day, tzinfo=timezone.utc) < end:
                stamp = day.isoformat()
                chunks.append(
                    (
                        _zip_text(session, f"{VISION}/daily/klines/{symbol}/15m/{symbol}-15m-{stamp}.zip"),
                        _zip_text(session, f"{VISION}/daily/fundingRate/{symbol}/{symbol}-fundingRate-{stamp}.zip"),
                    )
                )
                day += timedelta(days=1)
        for klines_text, funding_text in chunks:
            if klines_text:
                for row in _data_rows(klines_text):
                    opened = datetime.fromtimestamp(int(row[0]) / 1000, tz=timezone.utc)
                    if start <= opened < end:
                        klines.append(row[:6])
                        price_text.extend(row[1:5])
            if funding_text:
                for row in _data_rows(funding_text):
                    stamp = datetime.fromtimestamp(int(row[0]) / 1000, tz=timezone.utc)
                    if start <= stamp <= end:
                        funding.append((stamp, float(row[2])))
    funding.sort(key=lambda item: item[0])
    return klines, funding, _infer_tick(price_text)


def _infer_tick(prices: list[str]) -> str | None:
    step: Decimal | None = None
    for raw in prices:
        quantum = Decimal("1").scaleb(Decimal(raw).normalize().as_tuple().exponent)
        step = quantum if step is None else min(step, quantum)
    if step is None:
        return None
    return format(step, "f")


def _rest(symbol: str, start: datetime, end: datetime):
    raw = download_klines(symbol, "15m", start, end, market="usdm")
    funding = download_funding(symbol, start, end)
    try:
        payload = requests.get(
            base_url("usdm", False) + "/fapi/v1/exchangeInfo",
            params={"symbol": symbol},
            timeout=20,
        ).json()
        info = next(item for item in payload["symbols"] if item["symbol"] == symbol)
        found = {
            item["filterType"]: item
            for item in info["filters"]
            if item["filterType"] in ("PRICE_FILTER", "LOT_SIZE")
        }
    except (requests.RequestException, KeyError, StopIteration, ValueError) as exc:
        found = {"error": str(exc)}
    prices = [str(item[i]) for item in raw for i in (1, 2, 3, 4)]
    return raw, funding, found, _infer_tick(prices)


def main() -> None:
    end = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    start = end - timedelta(days=120)
    session = requests.Session()
    rows = []
    meta = {
        "start": start.isoformat(),
        "end": end.isoformat(),
        "symbols": {},
        "note": (
            "LOT_SIZE não vem no arquivo de klines. O tick abaixo é o menor incremento "
            "observado no preço, não o filtro oficial. O modo live recusa ordem se o "
            "exchangeInfo divergir do YAML."
        ),
    }
    source = "https://fapi.binance.com"
    for symbol in ("BTCUSDT", "ETHUSDT"):
        try:
            raw, funding, found, tick = _rest(symbol, start, end)
            origin = "fapi"
        except SafetyError as exc:
            print(f"{symbol}: REST indisponível ({exc}). Usando data.binance.vision.")
            raw, funding, tick = _vision(symbol, start, end, session)
            found = {"exchangeInfo": "HTTP 451 no fapi desta rede; tick inferido dos preços"}
            origin = "data.binance.vision"
            source = "https://data.binance.vision (USD-M futures)"
        bars = attach_funding([kline_to_bar(symbol, row, "15m") for row in raw], funding)
        closed = [bar for bar in bars if bar.ts + timedelta(minutes=15) <= end]
        for bar in closed:
            rows.append(
                {
                    "symbol": bar.symbol,
                    "ts": bar.ts.isoformat(),
                    "open": bar.open,
                    "high": bar.high,
                    "low": bar.low,
                    "close": bar.close,
                    "volume": bar.volume,
                    "timeframe": bar.timeframe,
                    "funding_rate": "" if bar.funding_rate is None else bar.funding_rate,
                }
            )
        meta["symbols"][symbol] = {
            "bars": len(closed),
            "funding_points": len(funding),
            "inferred_price_tick": tick,
            "origin": origin,
            "filters": found,
        }
        print(f"{symbol}: {len(closed)} barras, funding {len(funding)}, tick inferido {tick}")
    meta["source"] = source
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["symbol", "ts", "open", "high", "low", "close", "volume", "timeframe", "funding_rate"],
        )
        writer.writeheader()
        writer.writerows(rows)
    META.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"gravado {OUT}")


if __name__ == "__main__":
    main()
