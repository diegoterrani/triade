"""Fila, parâmetros e eventos do analista. Arquivos no diretório do agente, nada entre agentes."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from daytrade.common.errors import SafetyError
from daytrade.common.journal import Journal
from daytrade.common.llm_orders import coerce_param, llm_section

PARAM_ATTR = {
    "atr_mult": "atr_mult",
    "use_vwap_filter": "use_vwap_filter",
    "use_trend_filter": "use_trend_filter",
    "min_atr_pct": "min_atr_pct",
    "max_atr_pct": "max_atr_pct",
    "max_funding_long": "max_funding_long",
    "min_funding_short": "min_funding_short",
    "extension_k": "extension_k",
    "rearm_k": "rearm_k",
    "slope_max": "slope_max",
}


def llm_dir(directory: Path) -> Path:
    path = directory / "llm"
    path.mkdir(parents=True, exist_ok=True)
    return path


def control_path(directory: Path) -> Path:
    return llm_dir(directory) / "control.json"


def read_control(directory: Path) -> dict:
    path = directory / "llm" / "control.json"
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise SafetyError("control.json do analista está inválido")
    return data


def write_control(directory: Path, payload: dict) -> Path:
    path = control_path(directory)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)
    return path


def agent_enabled(cfg: dict, directory: Path) -> bool:
    control = read_control(directory)
    if "enabled" in control:
        return bool(control["enabled"])
    return bool((cfg.get("llm") or {}).get("enabled", True))


def set_enabled(cfg: dict, directory: Path, enabled: bool) -> dict:
    llm_section(cfg)
    control = read_control(directory)
    control["enabled"] = enabled
    control["updated_at"] = datetime.now(timezone.utc).isoformat()
    write_control(directory, control)
    _llm_journal(directory).write(
        "llm_decision",
        source="llm",
        action="enable" if enabled else "disable",
        rationale="analista ligou o agente" if enabled else "analista desligou entradas novas do agente",
    )
    return control


def set_param(cfg: dict, directory: Path, name: str, raw: object) -> dict:
    section = llm_section(cfg)
    bounds = (section.get("parameters") or {}).get(name)
    if bounds is None:
        raise SafetyError(f"parâmetro {name} não pode ser alterado pelo analista")
    value = coerce_param(name, raw, bounds)
    control = read_control(directory)
    params = dict(control.get("params") or {})
    params[name] = value
    control["params"] = params
    control["updated_at"] = datetime.now(timezone.utc).isoformat()
    write_control(directory, control)
    _llm_journal(directory).write(
        "llm_decision",
        source="llm",
        action="set-param",
        parameter=name,
        value=value,
        rationale=f"ajuste de {name} dentro da faixa do YAML",
    )
    return control


def apply_params(strategies: dict, params: dict, bounds: dict) -> dict[str, object]:
    applied: dict[str, object] = {}
    for name, raw in params.items():
        if name not in bounds:
            continue
        value = coerce_param(name, raw, bounds)
        attr = PARAM_ATTR.get(name, name)
        for strategy in set(strategies.values()):
            if hasattr(strategy, attr):
                setattr(strategy, attr, value)
        applied[name] = value
    return applied


def inbox_dir(directory: Path) -> Path:
    path = llm_dir(directory) / "inbox"
    path.mkdir(parents=True, exist_ok=True)
    return path


def result_path(directory: Path, key: str) -> Path:
    folder = llm_dir(directory) / "results"
    folder.mkdir(parents=True, exist_ok=True)
    return folder / f"{key}.json"


def read_result(directory: Path, key: str) -> dict | None:
    path = directory / "llm" / "results" / f"{key}.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def write_result(directory: Path, key: str, status: str, detail: str, order: dict | None = None) -> dict:
    payload = {
        "idempotency_key": key,
        "status": status,
        "detail": detail,
        "source": "llm",
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    if order:
        payload["order"] = order
    path = result_path(directory, key)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)
    return payload


def enqueue(directory: Path, order: dict) -> dict:
    key = order["idempotency_key"]
    existing = read_result(directory, key)
    if existing:
        return existing
    target = inbox_dir(directory) / f"{key}.json"
    temporary = target.with_suffix(".tmp")
    temporary.write_text(json.dumps(order, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(target)
    record = write_result(directory, key, "na_fila", "pedido aceito na fila; o risco ainda vai julgar", order)
    _llm_journal(directory).write(
        "llm_decision",
        source="llm",
        action="submit",
        status="na_fila",
        idempotency_key=key,
        symbol=order["symbol"],
        side=order["side"],
        qty=order["qty"],
        stop=order["stop"],
        take_profit=order.get("take_profit"),
        max_holding_minutes=order["max_holding_minutes"],
        rationale=order["rationale"],
    )
    return record


def write_event(directory: Path, kind: str, **fields: object) -> None:
    payload = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "kind": kind,
        **fields,
    }
    folder = directory / "events"
    folder.mkdir(parents=True, exist_ok=True)
    with (folder / "queue.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, default=str) + "\n")
    latest = folder / "latest.json"
    temporary = latest.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    temporary.replace(latest)


def _llm_journal(directory: Path) -> Journal:
    return Journal(directory / "journal" / "llm.jsonl")
