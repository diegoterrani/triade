"""Calendário da NYSE usado pelo agente de NASDAQ.

Feriados observados e o fechamento antecipado de 13:00. É uma aproximação do
calendário publicado pela bolsa: confira o ano corrente antes de ligar o live.
"""

from __future__ import annotations

from datetime import date, time, timedelta

from daytrade.common.calendar import good_friday


def _nth_weekday(year: int, month: int, weekday: int, n: int) -> date:
    first = date(year, month, 1)
    shift = (weekday - first.weekday()) % 7
    return first + timedelta(days=shift + 7 * (n - 1))


def _last_weekday(year: int, month: int, weekday: int) -> date:
    if month == 12:
        cursor = date(year + 1, 1, 1) - timedelta(days=1)
    else:
        cursor = date(year, month + 1, 1) - timedelta(days=1)
    return cursor - timedelta(days=(cursor.weekday() - weekday) % 7)


def _observed(day: date) -> date:
    if day.weekday() == 5:
        return day - timedelta(days=1)
    if day.weekday() == 6:
        return day + timedelta(days=1)
    return day


def nyse_holidays(year: int) -> set[date]:
    holidays = {
        _observed(date(year, 1, 1)),
        _nth_weekday(year, 1, 0, 3),
        _nth_weekday(year, 2, 0, 3),
        good_friday(year),
        _last_weekday(year, 5, 0),
        _observed(date(year, 6, 19)),
        _observed(date(year, 7, 4)),
        _nth_weekday(year, 9, 0, 1),
        _nth_weekday(year, 11, 3, 4),
        _observed(date(year, 12, 25)),
    }
    if date(year + 1, 1, 1).weekday() == 5:
        holidays.add(date(year, 12, 31))
    return holidays


def thanksgiving(year: int) -> date:
    return _nth_weekday(year, 11, 3, 4)


def is_nyse_holiday(day: date, extra_closed: set[date] | None = None) -> bool:
    if extra_closed and day in extra_closed:
        return True
    return day in nyse_holidays(day.year)


def early_close(day: date) -> time | None:
    """13:00 ET na véspera prática de feriado e na sexta depois do Thanksgiving."""
    if day.weekday() >= 5 or is_nyse_holiday(day):
        return None
    if day == thanksgiving(day.year) + timedelta(days=1):
        return time(13, 0)
    if day.month == 12 and day.day == 24:
        return time(13, 0)
    july4 = _observed(date(day.year, 7, 4))
    previous = july4 - timedelta(days=1)
    while previous.weekday() >= 5 or is_nyse_holiday(previous):
        previous -= timedelta(days=1)
    if day == previous and day.month == 7:
        return time(13, 0)
    return None


def session_checker(extra_closed: list[str] | None = None, extra_open: list[str] | None = None):
    closed = {date.fromisoformat(value) for value in (extra_closed or [])}
    opened = {date.fromisoformat(value) for value in (extra_open or [])}

    def is_session(day: date) -> bool:
        if day in opened:
            return True
        if day.weekday() >= 5:
            return False
        return not is_nyse_holiday(day, closed)

    return is_session
