"""Unidades systemd e o wrapper que tira o stdout do Wine das mãos do systemd."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from daytrade.common.config import project_root


def _root() -> Path:
    return project_root()


def _run(args: list[str], *, env: dict | None = None, **kwargs) -> subprocess.CompletedProcess:
    merged = os.environ.copy()
    merged.pop("WINEDEBUG", None)
    if env:
        merged.update(env)
    return subprocess.run(args, cwd=_root(), env=merged, text=True, **kwargs)


def test_setup_script_does_not_call_linger_or_enable_units():
    text = (_root() / "scripts/linux/setup-triade.sh").read_text(encoding="utf-8")
    code = "\n".join(line for line in text.splitlines() if not line.strip().startswith("#"))
    assert "loginctl" not in code
    assert "enable-linger" not in code
    assert "systemctl --user enable" not in code
    assert "systemctl --user disable" in code
    assert "run-agent.sh ${name} paper" in code
    assert "run-agent.sh crypto paper" in code
    assert "StandardOutput=append" not in code
    assert "StandardInput=null" in code


def test_units_only_writes_paper_bridges_without_systemd_stdio(tmp_path):
    dest = tmp_path / "units"
    proc = _run(
        ["bash", "scripts/linux/setup-triade.sh", "--units-only", "--no-systemctl"],
        env={"TRIADE_UNIT_DIR": str(dest)},
        capture_output=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    bridge = (dest / "triade-bridge-b3.service").read_text(encoding="utf-8")
    nasdaq = (dest / "triade-bridge-nasdaq.service").read_text(encoding="utf-8")
    agent = (dest / "triade-agent-b3.service").read_text(encoding="utf-8")
    crypto = (dest / "triade-agent-crypto.service").read_text(encoding="utf-8")
    xvfb = (dest / "triade-xvfb-b3.service").read_text(encoding="utf-8")
    assert "StandardOutput" not in bridge
    assert "StandardError" not in bridge
    assert "bridge.log" not in bridge
    assert "StandardInput=null" in bridge
    assert "run-bridge.sh b3" in bridge
    assert "127.0.0.1" in bridge
    assert "run-bridge.sh nasdaq" in nasdaq
    assert "Xvfb :71" in xvfb
    assert "Xvfb :72" in (dest / "triade-xvfb-nasdaq.service").read_text(encoding="utf-8")
    assert "run-agent.sh b3 paper" in agent
    assert "live" not in agent
    assert "run-agent.sh crypto paper" in crypto
    assert "live" not in crypto
    assert not list(dest.glob("*.wants"))
    assert "Linger não foi ativado" in proc.stdout


def test_print_launch_keeps_loopback_and_a_linux_log():
    env = {"TRIADE_PY": sys.executable}
    proc = _run(
        ["bash", "scripts/linux/run-bridge.sh", "--print-launch", "b3"],
        env=env,
        capture_output=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    fields = dict(line.split("=", 1) for line in proc.stdout.splitlines() if "=" in line)
    assert fields["host"] == "127.0.0.1"
    assert fields["port"] == "18861"
    assert fields["display"] == ":71"
    assert fields["stdin"] == "/dev/null"
    assert fields["stdio"] == "pty"
    assert fields["logger"] == "linux"
    assert fields["pythonunbuffered"] == "1"
    assert fields["winedebug"] == "-all"
    assert fields["log"].endswith("var/b3/logs/bridge.log")
    assert "--host" in fields["argv"] and "127.0.0.1" in fields["argv"]
    assert "--port" in fields["argv"] and "18861" in fields["argv"]
    assert "python.exe" in fields["argv"]
    assert "mt5_bridge_server.py" in fields["argv"]
    nasdaq = _run(
        ["bash", "scripts/linux/run-bridge.sh", "--print-launch", "nasdaq"],
        env=env,
        capture_output=True,
        check=True,
    )
    nasdaq_fields = dict(line.split("=", 1) for line in nasdaq.stdout.splitlines() if "=" in line)
    assert nasdaq_fields["port"] == "18862"
    assert nasdaq_fields["display"] == ":72"
    assert nasdaq_fields["host"] == "127.0.0.1"
    refused = _run(
        ["bash", "scripts/linux/run-bridge.sh", "--print-launch", "crypto"],
        env=env,
        capture_output=True,
        check=False,
    )
    assert refused.returncode == 2


def test_wine_stdio_hides_parent_stdout_and_returns_the_child_status(tmp_path):
    log = tmp_path / "bridge.log"
    parent_out = tmp_path / "systemd-append.log"
    code = (
        "import os, sys\n"
        "sys.stdout.write('tty %s\\n' % sys.stdout.isatty())\n"
        "sys.stdout.write('in %s\\n' % sys.stdin.isatty())\n"
        "sys.stdout.write('fd1 %s\\n' % os.readlink('/proc/self/fd/1'))\n"
        "sys.stdout.flush()\n"
    )
    with parent_out.open("ab") as stdout:
        proc = subprocess.run(
            [sys.executable, str(_root() / "scripts/linux/wine_stdio.py"), str(log), sys.executable, "-c", code],
            stdin=subprocess.DEVNULL,
            stdout=stdout,
            stderr=subprocess.STDOUT,
            timeout=10,
            check=False,
        )
    assert proc.returncode == 0
    written = log.read_bytes()
    assert b"tty True" in written
    assert b"in True" in written
    assert b"pts" in written
    leaked = parent_out.read_bytes()
    assert b"tty True" not in leaked

    status = subprocess.run(
        [sys.executable, str(_root() / "scripts/linux/wine_stdio.py"), str(log), sys.executable, "-c", "import sys; sys.exit(7)"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=10,
        check=False,
    )
    assert status.returncode == 7
    missing = subprocess.run(
        [sys.executable, str(_root() / "scripts/linux/wine_stdio.py"), str(tmp_path / "missing.log"), "triade-no-such-binary"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=10,
        check=False,
    )
    assert missing.returncode == 127
    assert b"exec falhou" in (tmp_path / "missing.log").read_bytes()
    usage = subprocess.run(
        [sys.executable, str(_root() / "scripts/linux/wine_stdio.py")],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert usage.returncode == 2


def test_shell_scripts_parse():
    root = _root() / "scripts/linux"
    for name in ("setup-triade.sh", "run-bridge.sh", "run-agent.sh"):
        proc = subprocess.run(["bash", "-n", str(root / name)], capture_output=True, text=True, check=False)
        assert proc.returncode == 0, proc.stderr
