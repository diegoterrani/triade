"""Retrato curto para o analista. Não é uma recomendação e não abre ordem."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from daytrade.common.indicators import atr_series
from daytrade.common.models import Bar
from daytrade.common.sessions import ensure_aware


def build_context(
    cfg: dict,
    *,
    now: datetime,
    bars: list[Bar],
    state: dict | None,
    control: dict,
    enabled: bool,
    kill_reason: str | None,
) -> dict:
    tz = ZoneInfo(cfg["timezone"])
    moment = ensure_aware(now, tz)
    state = state or {}
    grouped: dict[str, list[Bar]] = defaultdict(list)
    for bar in bars:
        grouped[bar.symbol].append(bar)
    symbols = {}
    for symbol, series in grouped.items():
        series = sorted(series, key=lambda item: item.ts)
        symbols[symbol] = _symbol_view(series, tz)
    positions = []
    for raw in state.get("positions") or []:
        positions.append(
            {
                "symbol": raw.get("symbol"),
                "qty": raw.get("qty"),
                "source": raw.get("source", "python"),
                "stop": raw.get("stop_price"),
                "opened_at": raw.get("opened_at"),
            }
        )
    risk = cfg.get("risk") or {}
    equity = float(state.get("day_start_equity") or risk.get("equity") or 0)
    pnl_today = float(state.get("realized_pnl_today") or 0)
    daily_limit = float(risk.get("daily_loss_limit_pct") or 0) * equity
    return {
        "agent": cfg.get("agent"),
        "profile": cfg.get("active_profile", "research"),
        "as_of": moment.isoformat(),
        "enabled": enabled,
        "kill": kill_reason,
        "halted": bool(state.get("halted")),
        "halt_reason": state.get("halt_reason"),
        "source_halted": state.get("source_halted") or {},
        "pnl_today": {
            "total": pnl_today,
            "by_source": state.get("pnl_by_source") or {},
        },
        "trades_today": {
            "total": int(state.get("trades_today") or 0),
            "by_source": state.get("trades_by_source") or {},
        },
        "risk_budget": {
            "equity_reference": equity,
            "daily_loss_limit": daily_limit,
            "daily_loss_left": daily_limit + pnl_today,
            "max_trades_per_day": int(risk.get("max_trades_per_day") or 0),
            "trades_left": int(risk.get("max_trades_per_day") or 0) - int(state.get("trades_today") or 0),
            "max_drawdown_pct": float(risk.get("max_drawdown_pct") or 0),
        },
        "positions": positions,
        "symbols": symbols,
        "upcoming_events": upcoming_events(cfg.get("agent", ""), moment),
        "params": control.get("params") or {},
        "note": "Retrato para o analista. Não é ordem e não fura o risco.",
    }


def upcoming_events(agent: str, moment: datetime) -> list[dict]:
    local = moment
    events: list[tuple[datetime, str]] = []
    if agent == "b3":
        events.extend(_today_clocks(local, [
            (time(8, 45), "leilão de abertura da B3"),
            (time(9, 0), "início da sessão contínua"),
            (time(10, 0), "prévia PTAX"),
            (time(11, 0), "prévia PTAX"),
            (time(12, 0), "prévia PTAX"),
            (time(13, 0), "prévia PTAX"),
            (time(18, 10), "zeragem do WIN"),
            (time(18, 25), "leilão de fechamento do WIN"),
        ]))
    elif agent == "nasdaq":
        events.extend(_today_clocks(local, [
            (time(8, 30), "janela de dado das 08:30 ET"),
            (time(9, 30), "abertura do caixa em Nova York"),
            (time(10, 0), "janela de dado das 10:00 ET"),
            (time(15, 45), "zeragem da sessão"),
        ]))
    elif agent == "crypto":
        utc = moment.astimezone(ZoneInfo("UTC"))
        for hour in (0, 8, 16):
            stamp = utc.replace(hour=hour, minute=0, second=0, microsecond=0)
            if stamp <= utc:
                stamp += timedelta(days=1)
            events.append((stamp, "funding da Binance USD-M"))
    horizon = moment + timedelta(hours=18)
    coming = [(stamp, label) for stamp, label in events if moment <= stamp <= horizon]
    coming.sort(key=lambda item: item[0])
    return [{"ts": stamp.isoformat(), "label": label} for stamp, label in coming[:8]]


def aggregate(bars: list[Bar], minutes: int) -> list[Bar]:
    if not bars or minutes <= 0:
        return []
    buckets: dict[datetime, list[Bar]] = defaultdict(list)
    for bar in bars:
        epoch = int(bar.ts.timestamp() // (minutes * 60)) * minutes * 60
        buckets[datetime.fromtimestamp(epoch, tz=bar.ts.tzinfo)].append(bar)
    merged = []
    for start, group in sorted(buckets.items()):
        group.sort(key=lambda item: item.ts)
        merged.append(
            Bar(
                symbol=group[0].symbol,
                ts=start,
                open=group[0].open,
                high=max(item.high for item in group),
                low=min(item.low for item in group),
                close=group[-1].close,
                volume=sum(item.volume for item in group),
                timeframe=f"{minutes}m",
            )
        )
    return merged


def _symbol_view(series: list[Bar], tz: ZoneInfo) -> dict:
    day = series[-1].ts.astimezone(tz).date()
    session = [bar for bar in series if bar.ts.astimezone(tz).date() == day]
    base = session or series
    vwap = _vwap(base)
    atr_values = atr_series(series, 14)
    atr = next((value for value in reversed(atr_values) if value is not None), None)
    recent_volume = [bar.volume for bar in series[-21:]]
    last_volume = recent_volume[-1] if recent_volume else 0
    baseline = recent_volume[:-1] or [0]
    average = sum(baseline) / len(baseline) if baseline else 0
    relative = (last_volume / average) if average else None
    return {
        "last": _bar_dict(series[-1]),
        "timeframes": {
            "base": [_bar_dict(bar) for bar in series[-8:]],
            "15m": [_bar_dict(bar) for bar in aggregate(series, 15)[-8:]],
            "60m": [_bar_dict(bar) for bar in aggregate(series, 60)[-8:]],
        },
        "vwap": vwap,
        "atr": atr,
        "relative_volume": relative,
        "volume_profile": _profile(base),
    }


def _vwap(bars: list[Bar]) -> float | None:
    total_pv = 0.0
    total_v = 0.0
    for bar in bars:
        typical = (bar.high + bar.low + bar.close) / 3
        volume = bar.volume if bar.volume > 0 else 1.0
        total_pv += typical * volume
        total_v += volume
    if total_v <= 0:
        return None
    return total_pv / total_v


def _profile(bars: list[Bar]) -> dict:
    if not bars:
        return {"poc": None, "bins": []}
    low = min(bar.low for bar in bars)
    high = max(bar.high for bar in bars)
    if high <= low:
        return {"poc": low, "bins": [{"price": low, "volume": sum(bar.volume for bar in bars)}]}
    width = (high - low) / 8
    bins = [{"price": low + (index + 0.5) * width, "volume": 0.0} for index in range(8)]
    for bar in bars:
        index = min(7, int((bar.close - low) / width))
        bins[index]["volume"] += bar.volume
    poc = max(bins, key=lambda item: item["volume"])
    return {"poc": poc["price"], "bins": bins}


def _bar_dict(bar: Bar) -> dict:
    return {
        "ts": bar.ts.isoformat(),
        "open": bar.open,
        "high": bar.high,
        "low": bar.low,
        "close": bar.close,
        "volume": bar.volume,
    }


def _today_clocks(moment: datetime, items: list[tuple[time, str]]) -> list[tuple[datetime, str]]:
    found = []
    for clock, label in items:
        stamp = moment.replace(hour=clock.hour, minute=clock.minute, second=0, microsecond=0)
        if stamp < moment:
            stamp += timedelta(days=1)
        found.append((stamp, label))
    return found
