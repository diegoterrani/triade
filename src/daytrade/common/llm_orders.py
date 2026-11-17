"""Pedido do analista. O schema é estreito de propósito: o que não está aqui é recusado.

A ordem só entra na fila. Quem arrisca, dimensiona e manda para a corretora é o
mesmo motor das estratégias Python.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

from daytrade.common.errors import SafetyError
from daytrade.common.models import Signal

_KEY = re.compile(r"^[A-Za-z0-9_-]{8,36}$")
_ALLOWED = {
    "idempotency_key",
    "symbol",
    "side",
    "qty",
    "entry_type",
    "stop",
    "take_profit",
    "max_holding_minutes",
    "rationale",
    "limit_price",
}
_REQUIRED = {"idempotency_key", "symbol", "side", "qty", "entry_type", "stop", "rationale"}


def llm_section(cfg: dict) -> dict:
    section = cfg.get("llm")
    if not isinstance(section, dict):
        raise SafetyError("o YAML deste agente não tem a seção llm")
    return section


def validate_order(payload: object, cfg: dict) -> dict:
    if not isinstance(payload, dict):
        raise SafetyError("o pedido do analista tem de ser um objeto JSON")
    unknown = sorted(set(payload) - _ALLOWED)
    if unknown:
        raise SafetyError(f"campo não permitido: {', '.join(unknown)}")
    missing = sorted(key for key in _REQUIRED if key not in payload)
    if missing:
        raise SafetyError(f"campo obrigatório ausente: {', '.join(missing)}")
    section = llm_section(cfg)
    key = payload["idempotency_key"]
    if not isinstance(key, str) or not _KEY.match(key):
        raise SafetyError("idempotency_key tem de ter 8 a 36 caracteres [A-Za-z0-9_-]")
    symbol = payload["symbol"]
    known = {spec["symbol"] for spec in cfg.get("symbols", [])}
    if symbol not in known:
        raise SafetyError(f"símbolo {symbol} não pertence a este agente")
    side = payload["side"]
    if side not in ("buy", "sell"):
        raise SafetyError("side tem de ser buy ou sell")
    entry_type = payload["entry_type"]
    if entry_type not in ("market", "limit"):
        raise SafetyError("entry_type tem de ser market ou limit")
    qty = _number(payload["qty"], "qty")
    if qty <= 0:
        raise SafetyError("qty tem de ser positiva")
    cap = (section.get("max_qty") or {}).get(symbol)
    if cap is not None and qty > float(cap) + 1e-12:
        raise SafetyError(f"quantidade acima do teto do analista para {symbol} ({cap})")
    stop = _number(payload["stop"], "stop")
    if stop <= 0:
        raise SafetyError("stop é obrigatório e tem de ser positivo")
    limit_price = None
    if entry_type == "limit":
        if "limit_price" not in payload:
            raise SafetyError("ordem limit exige limit_price")
        limit_price = _number(payload["limit_price"], "limit_price")
        if limit_price <= 0:
            raise SafetyError("limit_price tem de ser positivo")
    elif "limit_price" in payload:
        raise SafetyError("limit_price só vale em entry_type limit")
    take_profit = None
    if "take_profit" in payload and payload["take_profit"] is not None:
        take_profit = _number(payload["take_profit"], "take_profit")
        if take_profit <= 0:
            raise SafetyError("take_profit tem de ser positivo")
        if side == "buy" and take_profit <= stop:
            raise SafetyError("take_profit de compra tem de ficar acima do stop")
        if side == "sell" and take_profit >= stop:
            raise SafetyError("take_profit de venda tem de ficar abaixo do stop")
    low = int(section.get("min_holding_minutes", 30))
    high = int(section.get("max_holding_minutes", 240))
    if "max_holding_minutes" in payload and payload["max_holding_minutes"] is not None:
        holding = payload["max_holding_minutes"]
        if isinstance(holding, bool) or not isinstance(holding, int):
            raise SafetyError("max_holding_minutes tem de ser inteiro")
        if holding < low or holding > high:
            raise SafetyError(f"max_holding_minutes fora da faixa {low}–{high}")
    else:
        holding = high
    rationale = payload["rationale"]
    if not isinstance(rationale, str) or not rationale.strip():
        raise SafetyError("rationale é obrigatório")
    if len(rationale) > int(section.get("max_rationale_chars", 500)):
        raise SafetyError("rationale passa do tamanho permitido")
    return {
        "idempotency_key": key,
        "symbol": symbol,
        "side": side,
        "qty": qty,
        "entry_type": entry_type,
        "stop": stop,
        "take_profit": take_profit,
        "limit_price": limit_price,
        "max_holding_minutes": holding,
        "rationale": rationale.strip(),
    }


def signal_from_order(order: dict, ts: datetime) -> Signal:
    when = ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)
    return Signal(
        symbol=order["symbol"],
        ts=when,
        side=order["side"],
        reason=order["rationale"],
        strategy="llm_analyst",
        stop_price=order["stop"],
        target_price=order["take_profit"],
        immediate=False,
        source="llm",
        requested_qty=order["qty"],
        limit_price=order["limit_price"],
        max_hold_minutes=order["max_holding_minutes"],
        client_order_id=order["idempotency_key"],
        rationale=order["rationale"],
    )


def hold_deadline(opened_at: datetime, minutes: int | None) -> datetime | None:
    if not minutes:
        return None
    return opened_at + timedelta(minutes=minutes)


def coerce_param(name: str, raw: object, bounds: dict) -> object:
    if not isinstance(bounds, dict):
        raise SafetyError(f"parâmetro {name} não está na seção llm.parameters")
    if bounds.get("type") == "bool":
        if isinstance(raw, bool):
            return raw
        text = str(raw).strip().lower()
        if text in ("true", "1", "sim"):
            return True
        if text in ("false", "0", "nao", "não"):
            return False
        raise SafetyError(f"{name} é booleano")
    try:
        value = float(raw)
    except (TypeError, ValueError) as exc:
        raise SafetyError(f"{name} tem de ser numérico") from exc
    low = float(bounds["min"])
    high = float(bounds["max"])
    if value < low or value > high:
        raise SafetyError(f"{name} fora da faixa {low:g}–{high:g}")
    return value


def _number(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise SafetyError(f"{name} tem de ser numérico")
    return float(value)
