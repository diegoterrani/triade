"""Código do contrato corrente de WIN e WDO.

WIN: meses pares, vencimento na quarta-feira mais próxima do dia 15. Se esse dia
não tem pregão, vale a sessão seguinte. A distância nunca empata: a semana tem
sete dias, então uma das quartas é sempre mais perto.

WDO: vence no primeiro dia de pregão do mês. O último dia de negociação é a
sessão imediatamente anterior. A rolagem acontece quando restam até
`roll_sessions_before` sessões, inclusive o último pregão.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

from daytrade.b3.calendar import session_checker
from daytrade.common.symbols import SymbolRouter

MONTH_CODE = {
    1: "F",
    2: "G",
    3: "H",
    4: "J",
    5: "K",
    6: "M",
    7: "N",
    8: "Q",
    9: "U",
    10: "V",
    11: "X",
    12: "Z",
}


def wednesday_closest_to_15(year: int, month: int) -> date:
    target = date(year, month, 15)
    best: date | None = None
    best_distance = 99
    for delta in range(-6, 7):
        candidate = target + timedelta(days=delta)
        if candidate.weekday() != 2:
            continue
        distance = abs(delta)
        if distance < best_distance:
            best = candidate
            best_distance = distance
    if best is None:
        raise RuntimeError(f"sem quarta-feira perto de {target}")
    return best


def shift_to_session(day: date, is_session, direction: int) -> date:
    guard = 0
    while not is_session(day):
        day += timedelta(days=direction)
        guard += 1
        if guard > 20:
            raise RuntimeError(f"não achei pregão a partir de {day}")
    return day


def contract_code(root: str, expiration: date) -> str:
    return f"{root}{MONTH_CODE[expiration.month]}{expiration.year % 100:02d}"


def win_expiration(year: int, month: int, is_session) -> date:
    if month % 2 != 0:
        raise ValueError("WIN vence só em mês par")
    return shift_to_session(wednesday_closest_to_15(year, month), is_session, 1)


def wdo_expiration(year: int, month: int, is_session) -> date:
    return shift_to_session(date(year, month, 1), is_session, 1)


def wdo_last_trade(year: int, month: int, is_session) -> date:
    expiration = wdo_expiration(year, month, is_session)
    return shift_to_session(expiration - timedelta(days=1), is_session, -1)


def sessions_inclusive(start: date, end: date, is_session) -> int:
    if end < start:
        return 0
    count = 0
    day = start
    while day <= end:
        if is_session(day):
            count += 1
        day += timedelta(days=1)
    return count


def _add_months(year: int, month: int, step: int) -> tuple[int, int]:
    month += step
    while month > 12:
        month -= 12
        year += 1
    while month < 1:
        month += 12
        year -= 1
    return year, month


def active_contract(root: str, on: date, roll_sessions_before: int, is_session) -> str:
    root = root.upper()
    if root == "WIN":
        year, month = on.year, on.month
        year, month = _add_months(year, month, -1 if month % 2 else -2)
        for _ in range(8):
            expiration = win_expiration(year, month, is_session)
            left = sessions_inclusive(on, expiration, is_session)
            if left > roll_sessions_before:
                return contract_code("WIN", expiration)
            year, month = _add_months(year, month, 2)
        raise RuntimeError("não achei vencimento de WIN")
    if root == "WDO":
        year, month = _add_months(on.year, on.month, -1)
        for _ in range(8):
            last_trade = wdo_last_trade(year, month, is_session)
            expiration = wdo_expiration(year, month, is_session)
            if sessions_inclusive(on, last_trade, is_session) > roll_sessions_before:
                return contract_code("WDO", expiration)
            year, month = _add_months(year, month, 1)
        raise RuntimeError("não achei vencimento de WDO")
    raise ValueError(f"raiz desconhecida: {root}")


class B3SymbolRouter:
    def __init__(
        self,
        *,
        mode: str,
        continuous: dict[str, str],
        roll_sessions_before: int,
        is_session,
        suffix: str = "",
        tz_name: str = "America/Sao_Paulo",
    ) -> None:
        from zoneinfo import ZoneInfo

        self.mode = mode
        self.continuous = continuous
        self.roll_sessions_before = roll_sessions_before
        self.is_session = is_session
        self.suffix = suffix
        self.tz = ZoneInfo(tz_name)

    def venue(self, internal: str, ts: datetime) -> str:
        if self.mode == "continuous":
            base = self.continuous[internal]
        else:
            base = active_contract(
                internal,
                ts.astimezone(self.tz).date(),
                self.roll_sessions_before,
                self.is_session,
            )
        return f"{base}{self.suffix}"

    def internal(self, venue_symbol: str) -> str:
        name = venue_symbol
        if self.suffix and name.endswith(self.suffix):
            name = name[: -len(self.suffix)]
        for root, continuous in self.continuous.items():
            if name == continuous or name.startswith(root):
                return root
        return name


def router_from_config(cfg: dict) -> SymbolRouter:
    calendar_cfg = cfg.get("calendar") or {}
    checker = session_checker(calendar_cfg.get("extra_closed"), calendar_cfg.get("extra_open"))
    return B3SymbolRouter(
        mode=str(cfg.get("symbol_mode", "specific")),
        continuous=dict(cfg.get("continuous_symbols") or {"WIN": "WIN$", "WDO": "WDO$"}),
        roll_sessions_before=int(calendar_cfg.get("roll_sessions_before", 2)),
        is_session=checker,
        suffix=str(cfg.get("symbol_suffix") or ""),
        tz_name=cfg.get("timezone", "America/Sao_Paulo"),
    )
