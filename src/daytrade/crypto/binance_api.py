"""API oficial da Binance. A URL de testnet é escolhida pelo código, não por texto livre.

Backtest e paper simulado usam o mercado público de produção (klines). Ordem de
testnet nunca cai no host de produção, e ordem live nunca cai no host de testnet.
"""

from __future__ import annotations

import hashlib
import hmac
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

import requests

from daytrade.common.errors import Disconnect, EntryRolledBack, SafetyError
from daytrade.common.models import Bar, Fill, Instrument, OrderRequest

BASES = {
    ("spot", False): "https://api.binance.com",
    ("spot", True): "https://testnet.binance.vision",
    ("usdm", False): "https://fapi.binance.com",
    ("usdm", True): "https://testnet.binancefuture.com",
}
ORDER_PATH = {"spot": "/api/v3/order", "usdm": "/fapi/v1/order"}
KLINE_PATH = {"spot": "/api/v3/klines", "usdm": "/fapi/v1/klines"}
PING_PATH = {"spot": "/api/v3/ping", "usdm": "/fapi/v1/ping"}


def base_url(market: str, testnet: bool) -> str:
    try:
        return BASES[(market, testnet)]
    except KeyError as exc:
        raise SafetyError(f"mercado Binance desconhecido: {market}") from exc


def sign_query(secret: str, params: list[tuple[str, str]]) -> str:
    query = urlencode(params)
    signature = hmac.new(secret.encode(), query.encode(), hashlib.sha256).hexdigest()
    return f"{query}&signature={signature}"


def is_duplicate_client_order(payload: dict) -> bool:
    code = payload.get("code")
    message = str(payload.get("msg", "")).lower()
    return code in (-4116, -4015) or "duplicate" in message


def format_step(value: float, step: float) -> str:
    text = f"{step:.10f}".rstrip("0")
    decimals = len(text.split(".")[1]) if "." in text else 0
    return f"{value:.{decimals}f}"


def stop_client_id(entry_id: str) -> str:
    candidate = f"{entry_id}S"
    if len(candidate) <= 36:
        return candidate
    return hashlib.sha256(candidate.encode()).hexdigest()[:32]


def _get_json(session: requests.Session, url: str, params: dict | None = None) -> object:
    try:
        response = session.get(url, params=params, timeout=15)
    except requests.RequestException as exc:
        raise Disconnect(str(exc)) from exc
    if response.status_code >= 500 or response.status_code == 429:
        raise Disconnect(f"HTTP {response.status_code} em {url}")
    if response.status_code >= 400:
        raise SafetyError(f"HTTP {response.status_code}: {response.text[:300]}")
    return response.json()


def download_klines(
    symbol: str,
    interval: str,
    start: datetime,
    end: datetime,
    *,
    market: str = "usdm",
    session: requests.Session | None = None,
) -> list[list]:
    http = session or requests.Session()
    url = base_url(market, False) + KLINE_PATH[market]
    cursor = int(start.timestamp() * 1000)
    end_ms = int(end.timestamp() * 1000)
    rows: list[list] = []
    while cursor < end_ms:
        payload = _get_json(
            http,
            url,
            {"symbol": symbol, "interval": interval, "startTime": cursor, "endTime": end_ms, "limit": 1000},
        )
        if not isinstance(payload, list) or not payload:
            break
        rows.extend(payload)
        last_open = int(payload[-1][0])
        next_cursor = last_open + 1
        if next_cursor <= cursor:
            break
        cursor = next_cursor
        if len(payload) < 1000:
            break
    return rows


def download_funding(
    symbol: str,
    start: datetime,
    end: datetime,
    *,
    session: requests.Session | None = None,
) -> list[tuple[datetime, float]]:
    http = session or requests.Session()
    url = base_url("usdm", False) + "/fapi/v1/fundingRate"
    cursor = int(start.timestamp() * 1000)
    end_ms = int(end.timestamp() * 1000)
    points: list[tuple[datetime, float]] = []
    while cursor < end_ms:
        payload = _get_json(
            http,
            url,
            {"symbol": symbol, "startTime": cursor, "endTime": end_ms, "limit": 1000},
        )
        if not isinstance(payload, list) or not payload:
            break
        for item in payload:
            points.append(
                (datetime.fromtimestamp(int(item["fundingTime"]) / 1000, tz=timezone.utc), float(item["fundingRate"]))
            )
        last = int(payload[-1]["fundingTime"]) + 1
        if last <= cursor:
            break
        cursor = last
        if len(payload) < 1000:
            break
    return points


def kline_to_bar(symbol: str, row: list, timeframe: str, funding: float | None = None) -> Bar:
    return Bar(
        symbol=symbol,
        ts=datetime.fromtimestamp(int(row[0]) / 1000, tz=timezone.utc),
        open=float(row[1]),
        high=float(row[2]),
        low=float(row[3]),
        close=float(row[4]),
        volume=float(row[5]),
        timeframe=timeframe,
        funding_rate=funding,
    )


def attach_funding(bars: list[Bar], points: list[tuple[datetime, float]]) -> list[Bar]:
    if not points:
        return bars
    points = sorted(points, key=lambda item: item[0])
    index = 0
    current: float | None = None
    attached: list[Bar] = []
    for bar in bars:
        while index < len(points) and points[index][0] <= bar.ts:
            current = points[index][1]
            index += 1
        attached.append(
            Bar(
                symbol=bar.symbol,
                ts=bar.ts,
                open=bar.open,
                high=bar.high,
                low=bar.low,
                close=bar.close,
                volume=bar.volume,
                timeframe=bar.timeframe,
                funding_rate=current,
            )
        )
    return attached


class BinancePublicFeed:
    """Último candle já fechado. Sem chave. Paper simulado usa isto ou o replay."""

    def __init__(
        self,
        symbols: list[str],
        interval: str,
        market: str = "usdm",
        max_bars: int | None = None,
        testnet: bool = False,
    ) -> None:
        self.symbols = symbols
        self.interval = interval
        self.market = market
        self.testnet = testnet
        self.max_bars = max_bars
        self.idle_seconds = 3.0
        self.exhausted = False
        self.yielded = 0
        self.seen: set[tuple[str, datetime]] = set()
        self.queue: list[Bar] = []
        self._http = requests.Session()
        self._minutes = int(interval[:-1]) * (60 if interval.endswith("h") else 1)

    def poll(self) -> Bar | None:
        if self.max_bars is not None and self.yielded >= self.max_bars:
            self.exhausted = True
            return None
        if not self.queue:
            self._pull()
        if not self.queue:
            return None
        self.yielded += 1
        if self.max_bars is not None and self.yielded >= self.max_bars:
            self.exhausted = True
        return self.queue.pop(0)

    def reconnect(self) -> bool:
        url = base_url(self.market, self.testnet) + PING_PATH[self.market]
        for delay in (0.5, 1.0, 2.0, 4.0):
            try:
                _get_json(self._http, url)
                return True
            except Disconnect:
                time.sleep(delay)
        return False

    def _pull(self) -> None:
        url = base_url(self.market, self.testnet) + KLINE_PATH[self.market]
        now = datetime.now(timezone.utc)
        fresh: list[Bar] = []
        for symbol in self.symbols:
            payload = _get_json(self._http, url, {"symbol": symbol, "interval": self.interval, "limit": 2})
            if not isinstance(payload, list):
                continue
            for row in payload:
                bar = kline_to_bar(symbol, row, self.interval)
                if bar.ts + timedelta(minutes=self._minutes) > now:
                    continue
                key = (symbol, bar.ts)
                if key in self.seen:
                    continue
                self.seen.add(key)
                fresh.append(bar)
        fresh.sort(key=lambda bar: (bar.ts, bar.symbol))
        self.queue.extend(fresh)


class BinanceBroker:
    def __init__(
        self,
        *,
        market: str,
        testnet: bool,
        api_key: str,
        api_secret: str,
        instruments: dict[str, Instrument],
    ) -> None:
        if not api_key or not api_secret:
            raise SafetyError("chave da Binance ausente. Paper simulado não precisa de chave.")
        self.market = market
        self.testnet = testnet
        self.api_key = api_key
        self.api_secret = api_secret
        self.instruments = instruments
        self.base = base_url(market, testnet)
        self.last: dict[str, float] = {}
        self._http = requests.Session()
        self._equity_cache = 0.0

    def connect(self) -> None:
        self._check_filters()
        self._equity_cache = self._read_equity()

    def mark(self, symbol: str, price: float) -> None:
        self.last[symbol] = price

    def equity(self) -> float:
        try:
            self._equity_cache = self._read_equity()
        except Disconnect:
            if self._equity_cache <= 0:
                raise
        return self._equity_cache

    def positions(self) -> dict[str, float]:
        if self.market == "spot":
            payload = self._signed("GET", "/api/v3/account", [])
            totals = {}
            for item in payload.get("balances", []):
                symbol = f"{item['asset']}USDT"
                if symbol in self.instruments:
                    totals[symbol] = float(item["free"]) + float(item["locked"])
            return {symbol: qty for symbol, qty in totals.items() if qty > 0}
        payload = self._signed("GET", "/fapi/v2/positionRisk", [])
        totals = {}
        for item in payload:
            symbol = item["symbol"]
            if symbol not in self.instruments:
                continue
            qty = float(item["positionAmt"])
            if abs(qty) > 0:
                totals[symbol] = qty
        return totals

    def cancel_all(self) -> int:
        removed = 0
        for symbol in self.instruments:
            path = "/api/v3/openOrders" if self.market == "spot" else "/fapi/v1/allOpenOrders"
            try:
                self._signed("DELETE", path, [("symbol", symbol)])
                removed += 1
            except SafetyError:
                continue
        return removed

    def submit(self, order: OrderRequest, ref_price: float) -> Fill:
        if not order.reduce_only and order.stop_price is None:
            raise SafetyError("ordem de entrada sem stop")
        instrument = self.instruments[order.symbol]
        payload = self._place_market(order, instrument)
        if payload.get("status") not in (None, "FILLED", "NEW", "PARTIALLY_FILLED"):
            raise SafetyError(f"ordem não aceita: {payload.get('status')}")
        price = _fill_price(payload, ref_price)
        fill = Fill(
            client_order_id=order.client_order_id,
            symbol=order.symbol,
            side=order.side,
            qty=float(payload.get("executedQty") or order.qty),
            price=price,
            fee=instrument.fee(order.qty, price),
            ts=order.ts,
            reduce_only=order.reduce_only,
        )
        self.last[order.symbol] = price
        if not order.reduce_only and order.stop_price is not None:
            self._place_stop_or_rollback(order, instrument)
        return fill

    def attach_stop(self, symbol: str, qty: float, stop: float) -> None:
        instrument = self.instruments[symbol]
        side = "SELL" if qty > 0 else "BUY"
        self._place_stop(symbol, side, abs(qty), stop, instrument, f"adopt{symbol}{int(stop)}")

    def _place_market(self, order: OrderRequest, instrument: Instrument) -> dict:
        params = [
            ("symbol", order.symbol),
            ("side", "BUY" if order.side == "buy" else "SELL"),
            ("type", "MARKET"),
            ("quantity", format_step(order.qty, instrument.lot_step)),
            ("newClientOrderId", order.client_order_id),
            ("recvWindow", "5000"),
            ("timestamp", str(int(time.time() * 1000))),
        ]
        if self.market == "usdm" and order.reduce_only:
            params.insert(4, ("reduceOnly", "true"))
        payload = self._signed("POST", ORDER_PATH[self.market], params)
        if isinstance(payload, dict) and is_duplicate_client_order(payload):
            return self._fetch_order(order.symbol, order.client_order_id)
        return payload

    def _place_stop_or_rollback(self, order: OrderRequest, instrument: Instrument) -> None:
        exit_side = "SELL" if order.side == "buy" else "BUY"
        try:
            self._place_stop(
                order.symbol,
                exit_side,
                order.qty,
                float(order.stop_price),
                instrument,
                stop_client_id(order.client_order_id),
            )
        except (SafetyError, Disconnect) as exc:
            try:
                self._emergency_close(order, instrument, exit_side)
            except (SafetyError, Disconnect) as close_exc:
                raise SafetyError(
                    "o stop não fixou e a zeragem de emergência também falhou. Confira a conta antes de religar."
                ) from close_exc
            raise EntryRolledBack(f"stop não fixou; posição zerada ({exc})") from exc

    def _place_stop(self, symbol: str, side: str, qty: float, stop: float, instrument: Instrument, client_id: str) -> None:
        if self.market == "usdm":
            params = [
                ("symbol", symbol),
                ("side", side),
                ("type", "STOP_MARKET"),
                ("stopPrice", format_step(stop, instrument.tick_size)),
                ("closePosition", "true"),
                ("workingType", "CONTRACT_PRICE"),
                ("newClientOrderId", client_id[:36]),
                ("recvWindow", "5000"),
                ("timestamp", str(int(time.time() * 1000))),
            ]
        else:
            limit = stop - instrument.tick_size if side == "SELL" else stop + instrument.tick_size
            params = [
                ("symbol", symbol),
                ("side", side),
                ("type", "STOP_LOSS_LIMIT"),
                ("timeInForce", "GTC"),
                ("quantity", format_step(qty, instrument.lot_step)),
                ("price", format_step(limit, instrument.tick_size)),
                ("stopPrice", format_step(stop, instrument.tick_size)),
                ("newClientOrderId", client_id[:36]),
                ("recvWindow", "5000"),
                ("timestamp", str(int(time.time() * 1000))),
            ]
        payload = self._signed("POST", ORDER_PATH[self.market], params)
        if isinstance(payload, dict) and payload.get("code") and not is_duplicate_client_order(payload):
            raise SafetyError(str(payload.get("msg", "falha ao criar stop")))

    def _emergency_close(self, order: OrderRequest, instrument: Instrument, side: str) -> None:
        params = [
            ("symbol", order.symbol),
            ("side", side),
            ("type", "MARKET"),
            ("quantity", format_step(order.qty, instrument.lot_step)),
            ("newClientOrderId", stop_client_id(order.client_order_id + "X")[:36]),
            ("recvWindow", "5000"),
            ("timestamp", str(int(time.time() * 1000))),
        ]
        if self.market == "usdm":
            params.insert(4, ("reduceOnly", "true"))
        self._signed("POST", ORDER_PATH[self.market], params)

    def _fetch_order(self, symbol: str, client_id: str) -> dict:
        path = "/api/v3/order" if self.market == "spot" else "/fapi/v1/order"
        return self._signed(
            "GET",
            path,
            [("symbol", symbol), ("origClientOrderId", client_id), ("timestamp", str(int(time.time() * 1000)))],
        )

    def _read_equity(self) -> float:
        if self.market == "spot":
            payload = self._signed("GET", "/api/v3/account", [("timestamp", str(int(time.time() * 1000)))])
            for item in payload.get("balances", []):
                if item["asset"] == "USDT":
                    return float(item["free"]) + float(item["locked"])
            return 0.0
        payload = self._signed("GET", "/fapi/v2/account", [("timestamp", str(int(time.time() * 1000)))])
        return float(payload.get("totalWalletBalance") or payload.get("totalMarginBalance") or 0.0)

    def _check_filters(self) -> None:
        path = "/api/v3/exchangeInfo" if self.market == "spot" else "/fapi/v1/exchangeInfo"
        for symbol, instrument in self.instruments.items():
            payload = _get_json(self._http, self.base + path, {"symbol": symbol})
            info = _symbol_info(payload, symbol)
            tick, step, min_qty = _filters(info)
            if tick != instrument.tick_size or step != instrument.lot_step:
                raise SafetyError(
                    f"{symbol}: filtro da Binance é tick {tick} step {step}, "
                    f"mas o config tem tick {instrument.tick_size} step {instrument.lot_step}."
                )
            if min_qty > instrument.min_qty:
                raise SafetyError(f"{symbol}: lote mínimo da Binance ({min_qty}) é maior que o config.")

    def _signed(self, method: str, path: str, params: list[tuple[str, str]]) -> dict:
        if not any(key == "timestamp" for key, _ in params):
            params = [*params, ("timestamp", str(int(time.time() * 1000)))]
        signed = sign_query(self.api_secret, params)
        try:
            response = self._http.request(
                method,
                self.base + path + "?" + signed,
                headers={"X-MBX-APIKEY": self.api_key},
                timeout=15,
            )
        except requests.RequestException as exc:
            raise Disconnect(str(exc)) from exc
        try:
            payload = response.json()
        except ValueError as exc:
            raise Disconnect(f"resposta inválida da Binance ({response.status_code})") from exc
        if response.status_code >= 500 or response.status_code == 429:
            raise Disconnect(f"HTTP {response.status_code}")
        if isinstance(payload, dict) and payload.get("code") and response.status_code >= 400:
            if is_duplicate_client_order(payload):
                return payload
            raise SafetyError(str(payload.get("msg", payload.get("code"))))
        if not isinstance(payload, dict):
            return {"raw": payload}
        return payload


def _symbol_info(payload: object, symbol: str) -> dict:
    if not isinstance(payload, dict):
        raise SafetyError("exchangeInfo ilegível")
    for item in payload.get("symbols", []):
        if item.get("symbol") == symbol:
            return item
    raise SafetyError(f"{symbol} não voltou no exchangeInfo")


def _filters(info: dict) -> tuple[float, float, float]:
    tick = step = min_qty = None
    for item in info.get("filters", []):
        if item.get("filterType") == "PRICE_FILTER":
            tick = float(item["tickSize"])
        if item.get("filterType") == "LOT_SIZE":
            step = float(item["stepSize"])
            min_qty = float(item["minQty"])
    if tick is None or step is None or min_qty is None:
        raise SafetyError("PRICE_FILTER ou LOT_SIZE ausente")
    return tick, step, min_qty


def _fill_price(payload: dict, ref_price: float) -> float:
    if payload.get("avgPrice") not in (None, "", "0", "0.0", "0.00"):
        try:
            value = float(payload["avgPrice"])
            if value > 0:
                return value
        except (TypeError, ValueError):
            pass
    if payload.get("price") not in (None, "", "0"):
        try:
            value = float(payload["price"])
            if value > 0:
                return value
        except (TypeError, ValueError):
            pass
    return ref_price
