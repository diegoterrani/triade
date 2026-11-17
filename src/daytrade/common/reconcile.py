"""Reconciliação. Divergência bloqueia entrada nova; não inventa ordem para 'corrigir' tamanho."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ReconcileResult:
    ok: bool
    mismatches: list[str] = field(default_factory=list)
    adopted: list[str] = field(default_factory=list)


def reconcile(
    local: dict[str, float],
    remote: dict[str, float],
    *,
    qty_tol: float = 1e-8,
) -> ReconcileResult:
    mismatches: list[str] = []
    adopted: list[str] = []
    for symbol in sorted(set(local) | set(remote)):
        left = float(local.get(symbol, 0.0))
        right = float(remote.get(symbol, 0.0))
        if abs(left - right) <= qty_tol:
            continue
        mismatches.append(f"{symbol}: local={left} corretora={right}")
        if abs(left) <= qty_tol and abs(right) > qty_tol:
            adopted.append(symbol)
    return ReconcileResult(ok=not mismatches, mismatches=mismatches, adopted=adopted)
