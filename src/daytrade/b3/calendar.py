"""Calendário de sessão da B3.

Inclui feriados nacionais, aniversário de São Paulo, Carnaval, Sexta-feira Santa
e Corpus Christi. 24 e 31 de dezembro entram como dia sem pregão, que é a prática
recente da bolsa. A lista oficial do ano manda: use extra_closed e extra_open.
"""

from __future__ import annotations

from datetime import date, timedelta

from daytrade.common.calendar import easter_sunday, good_friday


def b3_holidays(year: int) -> set[date]:
    easter = easter_sunday(year)
    carnival_tuesday = easter - timedelta(days=47)
    carnival_monday = carnival_tuesday - timedelta(days=1)
    corpus_christi = easter + timedelta(days=60)
    return {
        date(year, 1, 1),
        date(year, 1, 25),
        carnival_monday,
        carnival_tuesday,
        good_friday(year),
        date(year, 4, 21),
        date(year, 5, 1),
        corpus_christi,
        date(year, 9, 7),
        date(year, 10, 12),
        date(year, 11, 2),
        date(year, 11, 15),
        date(year, 11, 20),
        date(year, 12, 24),
        date(year, 12, 25),
        date(year, 12, 31),
    }


def session_checker(extra_closed: list[str] | None = None, extra_open: list[str] | None = None):
    closed = {date.fromisoformat(value) for value in (extra_closed or [])}
    opened = {date.fromisoformat(value) for value in (extra_open or [])}
    cache: dict[int, set[date]] = {}

    def is_session(day: date) -> bool:
        if day in opened:
            return True
        if day.weekday() >= 5 or day in closed:
            return False
        holidays = cache.get(day.year)
        if holidays is None:
            holidays = b3_holidays(day.year)
            cache[day.year] = holidays
        return day not in holidays

    return is_session
