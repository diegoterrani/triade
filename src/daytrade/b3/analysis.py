"""Estratégia inicial do agente B3: rompimento da abertura.

A janela começa depois do leilão (o config traz 09:05). WIN e WDO usam a mesma
ideia, com zeragem e bloqueio de PTAX próprios de cada símbolo. Novo estudo entra
no dicionário STRATEGIES sem mexer na execução.
"""

from __future__ import annotations

from datetime import date, time
from zoneinfo import ZoneInfo

from daytrade.b3.calendar import session_checker
from daytrade.common.sessions import parse_hhmm
from daytrade.common.strategies import OpeningRangeBreakout


def _windows(raw: list | None) -> list[tuple[time, time]]:
    windows = []
    for start, end in raw or []:
        windows.append((parse_hhmm(start), parse_hhmm(end)))
    return windows


def build_strategy(cfg: dict) -> OpeningRangeBreakout:
    params = cfg["strategy"]
    name = params.get("name", "orb_vwap_trend")
    if name != "orb_vwap_trend":
        known = ", ".join(sorted(STRATEGIES))
        raise ValueError(f"estratégia {name} não existe neste agente. Disponíveis: {known}")
    calendar_cfg = cfg.get("calendar") or {}
    is_session = session_checker(calendar_cfg.get("extra_closed"), calendar_cfg.get("extra_open"))
    flatten_by_symbol: dict[str, time] = {}
    no_new_by_symbol: dict[str, time] = {}
    blackouts_by_symbol: dict[str, list[tuple[time, time]]] = {}
    for spec in cfg["symbols"]:
        symbol = spec["symbol"]
        if spec.get("flatten_time"):
            flatten_by_symbol[symbol] = parse_hhmm(spec["flatten_time"])
        if spec.get("no_new_trades_after"):
            no_new_by_symbol[symbol] = parse_hhmm(spec["no_new_trades_after"])
        if spec.get("blackouts"):
            blackouts_by_symbol[symbol] = _windows(spec["blackouts"])
    return OpeningRangeBreakout(
        name="orb_vwap_trend",
        tz=ZoneInfo(cfg["timezone"]),
        range_start=parse_hhmm(params["range_start"]),
        orb_minutes=int(params["orb_minutes"]),
        flatten_time=parse_hhmm(params["flatten_time"]),
        no_new_trades_after=parse_hhmm(params["no_new_trades_after"]),
        ema_fast=int(params["ema_fast"]),
        ema_slow=int(params["ema_slow"]),
        atr_period=int(params["atr_period"]),
        atr_mult=float(params["atr_mult"]),
        use_vwap_filter=bool(params.get("use_vwap_filter", True)),
        use_trend_filter=bool(params.get("use_trend_filter", True)),
        one_trade_per_day=bool(params.get("one_trade_per_day", True)),
        flatten_by_symbol=flatten_by_symbol,
        no_new_by_symbol=no_new_by_symbol,
        blackouts_by_symbol=blackouts_by_symbol,
        is_holiday=lambda day: not is_session(day),
    )


STRATEGIES = {"orb_vwap_trend": build_strategy}


def build_strategies(cfg: dict) -> dict[str, OpeningRangeBreakout]:
    strategy = build_strategy(cfg)
    return {spec["symbol"]: strategy for spec in cfg["symbols"]}
