from __future__ import annotations

import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from daytrade.common.config import load_config, project_root
from daytrade.kill import main as kill_main


def _write_csv(path: Path, symbol: str, start: datetime) -> None:
    lines = ["symbol,ts,open,high,low,close,volume,timeframe,funding_rate"]
    ts = start
    price = 100.0
    for _ in range(4):
        lines.append(f"{symbol},{ts.isoformat()},{price},{price+1},{price-1},{price+0.2},1000,5m,")
        ts = ts.replace(minute=ts.minute)  # keep the object
        from datetime import timedelta

        ts = ts + timedelta(minutes=5)
        price += 0.2
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_three_paper_processes_use_separate_state(tmp_path):
    from daytrade.b3.execution import run_realtime as b3_run
    from daytrade.crypto.execution import run_realtime as crypto_run
    from daytrade.nasdaq.execution import run_realtime as nasdaq_run

    b3_csv = tmp_path / "b3.csv"
    crypto_csv = tmp_path / "crypto.csv"
    nasdaq_csv = tmp_path / "nasdaq.csv"
    _write_csv(b3_csv, "WIN", datetime(2024, 8, 5, 9, 0, tzinfo=ZoneInfo("America/Sao_Paulo")))
    _write_csv(crypto_csv, "BTCUSDT", datetime(2024, 8, 5, 12, 0, tzinfo=ZoneInfo("UTC")))
    _write_csv(nasdaq_csv, "USTEC", datetime(2024, 9, 3, 9, 30, tzinfo=ZoneInfo("America/New_York")))
    # segunda linha WDO para o agente B3 não reclamar de símbolo desconhecido — ele não reclama.
    specs = [
        (b3_run, "configs/b3.yaml", b3_csv, tmp_path / "b3"),
        (crypto_run, "configs/crypto.yaml", crypto_csv, tmp_path / "crypto"),
        (nasdaq_run, "configs/nasdaq.yaml", nasdaq_csv, tmp_path / "nasdaq"),
    ]
    for runner, config, csv_path, state in specs:
        cfg = load_config(config)
        cfg["paths"]["state_dir"] = str(state)
        cfg["feed"]["kind"] = "replay"
        assert runner(cfg, "paper", 4, str(csv_path)) == 0
        assert (state / "logs" / "paper.jsonl").exists()
        assert (state / "journal" / "paper.jsonl").exists()
    assert not (tmp_path / "b3" / "logs" / "paper.jsonl").read_text(encoding="utf-8").count('"agent": "crypto"')


def test_kill_command_writes_and_clears_flags(tmp_path, monkeypatch):
    monkeypatch.setattr("daytrade.kill.project_root", lambda: tmp_path)
    assert kill_main(["b3", "--reason", "teste"]) == 0
    assert (tmp_path / "var" / "b3" / "KILL").read_text(encoding="utf-8").strip() == "teste"
    assert kill_main(["--all", "--reason", "global"]) == 0
    assert (tmp_path / "var" / "KILL_ALL").exists()
    assert kill_main(["--all", "--clear"]) == 0
    assert not (tmp_path / "var" / "KILL_ALL").exists()
    assert not (tmp_path / "var" / "b3" / "KILL").exists()


def test_live_command_is_refused_without_the_two_latches():
    env = os.environ.copy()
    env.pop("DAYTRADE_LIVE_CONFIRM", None)
    result = subprocess.run(
        [sys.executable, "-m", "daytrade.crypto", "live", "--config", "configs/crypto.yaml"],
        cwd=project_root(),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 2
    assert "live_enabled" in result.stdout


def test_agent_refuses_another_agents_config():
    env = os.environ.copy()
    result = subprocess.run(
        [sys.executable, "-m", "daytrade.b3", "status", "--config", "configs/crypto.yaml"],
        cwd=project_root(),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 2
    assert "não é deste agente" in result.stdout or "não de b3" in result.stdout
