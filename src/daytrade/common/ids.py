"""Identificador de ordem estável. A mesma intenção gera o mesmo id, então um retry não duplica."""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone

_UNSAFE = re.compile(r"[^A-Za-z0-9_-]")


def client_order_id(agent: str, symbol: str, ts: datetime, side: str, kind: str) -> str:
    stamp = ts.astimezone(timezone.utc).strftime("%Y%m%d%H%M")
    side_code = {"buy": "b", "sell": "s", "flat": "f"}.get(side, "x")
    kind_code = {"entry": "e", "exit": "x", "stop": "s", "flatten": "z"}.get(kind, "q")
    raw = _UNSAFE.sub("", f"{agent[:4]}{symbol}{stamp}{side_code}{kind_code}")
    if len(raw) <= 36:
        return raw
    digest = hashlib.sha256(raw.encode()).hexdigest()[:16]
    return f"{agent[:4]}{digest}"[:36]
