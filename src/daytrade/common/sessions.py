"""Janelas de horário. O relógio é sempre o do mercado, nunca o relógio da máquina."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo


def parse_hhmm(value: str) -> time:
    parts = value.strip().split(":")
    if len(parts) != 2:
        raise ValueError(f"horário inválido: {value}")
    hour, minute = int(parts[0]), int(parts[1])
    return time(hour, minute)


def add_minutes(value: time, minutes: int) -> time:
    base = datetime(2000, 1, 1, value.hour, value.minute, value.second)
    return (base + timedelta(minutes=minutes)).time()


def in_half_open(value: time, start: time, end: time) -> bool:
    """Intervalo [start, end). Não atravessa meia-noite."""
    return start <= value < end


def local_clock(ts: datetime, tz: ZoneInfo) -> tuple[date, time]:
    local = ts.astimezone(tz)
    return local.date(), local.timetz().replace(tzinfo=None)


def ensure_aware(ts: datetime, tz: ZoneInfo) -> datetime:
    if ts.tzinfo is None:
        return ts.replace(tzinfo=tz)
    return ts.astimezone(tz)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)
