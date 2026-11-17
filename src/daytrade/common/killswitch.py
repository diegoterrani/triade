"""Kill switch por arquivo. O processo do agente só observa o próprio diretório e o flag global.

Não há comunicação entre agentes. O comando global apenas grava outro arquivo.
"""

from __future__ import annotations

from pathlib import Path


class KillSwitch:
    def __init__(self, agent: str, root: Path, *, enabled: bool = True) -> None:
        self.agent = agent
        self.root = root
        self.enabled = enabled
        self.agent_flag = root / agent / "KILL"
        self.global_flag = root / "KILL_ALL"

    def tripped(self) -> str | None:
        if not self.enabled:
            return None
        if self.global_flag.exists():
            return _read(self.global_flag) or "KILL_ALL"
        if self.agent_flag.exists():
            return _read(self.agent_flag) or f"KILL {self.agent}"
        return None

    def trip(self, reason: str, *, global_: bool = False) -> Path:
        flag = self.global_flag if global_ else self.agent_flag
        flag.parent.mkdir(parents=True, exist_ok=True)
        flag.write_text(reason.strip() + "\n", encoding="utf-8")
        return flag

    def clear(self, *, global_: bool = False) -> bool:
        flag = self.global_flag if global_ else self.agent_flag
        if flag.exists():
            flag.unlink()
            return True
        return False


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8").strip()[:500]
    except OSError:
        return ""
