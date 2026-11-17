#!/usr/bin/env python3
"""Console para o Python do Wine e log gravado no Linux.

O Python de Windows morre antes do programa quando o stdout vem do systemd:

    Fatal Python error: init_sys_streams: can't initialize sys standard streams
    OSError: [WinError 6] Invalid handle

O fstat daquele handle (StandardOutput=append) não vale dentro do Wine. Este
processo não entrega esses descritores ao filho. O filho fica num pty, que o
Wine enxerga como console, e este processo (stdin em /dev/null) copia a saída
para o arquivo de log.
"""

from __future__ import annotations

import errno
import os
import pty
import resource
import select
import signal
import sys


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) < 2:
        print("uso: wine_stdio.py ARQUIVO_DE_LOG COMANDO [ARGS...]", file=sys.stderr)
        return 2
    log_path = args[0]
    command = args[1:]
    directory = os.path.dirname(log_path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    log_fd = os.open(log_path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
    try:
        _write_all(log_fd, ("wine_stdio " + " ".join(command) + "\n").encode())
        return _run(log_fd, command)
    finally:
        os.close(log_fd)


def _run(log_fd: int, command: list[str]) -> int:
    pid, master = pty.fork()
    if pid == 0:
        _child(command)
        os._exit(127)
    null_fd = os.open(os.devnull, os.O_RDONLY)
    if null_fd != 0:
        os.dup2(null_fd, 0)
        os.close(null_fd)
    _forward_stop_signals(pid)
    try:
        return _pump(master, log_fd, pid)
    finally:
        os.close(master)


def _child(command: list[str]) -> None:
    soft, _hard = resource.getrlimit(resource.RLIMIT_NOFILE)
    limit = soft if 3 < soft < 65536 else 1024
    os.closerange(3, limit)
    try:
        os.execvp(command[0], command)
    except OSError as exc:
        try:
            os.write(2, f"exec falhou: {exc}\n".encode())
        except OSError:
            pass
    os._exit(127)


def _forward_stop_signals(pid: int) -> None:
    def forward(signum, _frame) -> None:
        try:
            os.kill(pid, signum)
        except ProcessLookupError:
            pass

    for signum in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
        signal.signal(signum, forward)
    signal.signal(signal.SIGWINCH, signal.SIG_IGN)


def _pump(master: int, log_fd: int, pid: int) -> int:
    while True:
        try:
            ready, _, _ = select.select([master], [], [], 0.25)
        except InterruptedError:
            ready = []
        if master in ready:
            try:
                chunk = os.read(master, 65536)
            except OSError as exc:
                if exc.errno == errno.EIO:
                    return _reap(pid)
                if exc.errno == errno.EINTR:
                    continue
                raise
            if not chunk:
                return _reap(pid)
            _write_all(log_fd, chunk)
            continue
        done, status = os.waitpid(pid, os.WNOHANG)
        if done:
            _drain(master, log_fd)
            return _exit_code(status)


def _drain(master: int, log_fd: int) -> None:
    while True:
        try:
            ready, _, _ = select.select([master], [], [], 0)
        except InterruptedError:
            continue
        if master not in ready:
            return
        try:
            chunk = os.read(master, 65536)
        except OSError as exc:
            if exc.errno in (errno.EIO, errno.EBADF):
                return
            raise
        if not chunk:
            return
        _write_all(log_fd, chunk)


def _reap(pid: int) -> int:
    _done, status = os.waitpid(pid, 0)
    return _exit_code(status)


def _exit_code(status: int) -> int:
    if os.WIFEXITED(status):
        return os.WEXITSTATUS(status)
    if os.WIFSIGNALED(status):
        return 128 + os.WTERMSIG(status)
    return 1


def _write_all(fd: int, data: bytes) -> None:
    view = memoryview(data)
    while view:
        written = os.write(fd, view)
        view = view[written:]


if __name__ == "__main__":
    raise SystemExit(main())
