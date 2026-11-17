"""Trava do modo live: flag no config E variável de ambiente.

As duas precisam estar presentes. O valor da variável é fixo de propósito,
para não ser ligado por um export acidental de '1' ou 'true'.
"""

from __future__ import annotations

import os
from collections.abc import Mapping

from daytrade.common.errors import LiveGateError

CONFIRM_VALUE = "I_UNDERSTAND_REAL_MONEY"
CONFIRM_ENV = "DAYTRADE_LIVE_CONFIRM"


def assert_live_allowed(
    agent: str,
    live_enabled: bool,
    env: Mapping[str, str] | None = None,
) -> None:
    source = os.environ if env is None else env
    if not live_enabled:
        raise LiveGateError(
            f"Agente {agent}: live_enabled está false. O padrão seguro é paper. "
            "Só ligue o flag no config deste agente depois do checklist."
        )
    got = source.get(CONFIRM_ENV, "")
    if got != CONFIRM_VALUE:
        raise LiveGateError(
            f"Agente {agent}: para enviar ordens reais defina {CONFIRM_ENV}={CONFIRM_VALUE}. "
            "Essa variável fica fora do git."
        )
