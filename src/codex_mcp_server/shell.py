from __future__ import annotations

import os
import selectors
import signal
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class ExecSession:
    session_id: int
    process: subprocess.Popen[bytes]
    output_fd: int
    stdin_fd: int | None
    command: str
    started_at: float = field(default_factory=time.monotonic)
    buffer: bytearray = field(default_factory=bytearray)


class ShellManager:
    def __init__(self, cwd: Path) -> None:
        self.cwd = cwd
        self.sessions: dict[int, ExecSession] = {}
        self._next_session_id = 1

    def exec_command(self, args: dict[str, Any]) -> dict[str, Any]:
        cmd = require_string(args, "cmd")
        workdir = Path(args.get("workdir") or self.cwd).expanduser()
        if not workdir.is_absolute():
            workdir = self.cwd / workdir
        workdir = workdir.resolve()
        if not workdir.exists():
            raise ValueError(f"workdir does not exist: {workdir}")

        tty = bool(args.get("tty", False))
        yield_ms = clamp_int(args.get("yield_time_ms", 10000), 250, 30000)
        max_output_tokens = clamp_int(args.get("max_output_tokens", 10000), 100, 100000)
        shell = args.get("shell") or os.environ.get("SHELL") or "/bin/bash"
        login = bool(args.get("login", True))
        argv = shell_argv(str(shell), cmd, login)

        if tty:
            session = self._spawn_pty(argv, workdir, cmd)
        else:
            session = self._spawn_pipe(argv, workdir, cmd)
        self.sessions[session.session_id] = session
        return self._wait_and_collect(session, yield_ms, max_output_tokens, remove_finished=True)

    def write_stdin(self, args: dict[str, Any]) -> dict[str, Any]:
        session_id = int(args.get("session_id"))
        session = self.sessions.get(session_id)
        if session is None:
            raise ValueError(f"Unknown or completed session_id: {session_id}")
        chars = args.get("chars", "")
        if chars is None:
            chars = ""
        if not isinstance(chars, str):
            raise ValueError("chars must be a string when provided")
        default_wait = 250 if chars else 5000
        max_wait = 30000 if chars else 300000
        yield_ms = clamp_int(args.get("yield_time_ms", default_wait), 250, max_wait)
        max_output_tokens = clamp_int(args.get("max_output_tokens", 10000), 100, 100000)

        if chars:
            if session.stdin_fd is None:
                raise ValueError("stdin is closed for this session")
            os.write(session.stdin_fd, chars.encode())
        return self._wait_and_collect(session, yield_ms, max_output_tokens, remove_finished=True)

    def _spawn_pipe(self, argv: list[str], workdir: Path, command: str) -> ExecSession:
        process = subprocess.Popen(
            argv,
            cwd=str(workdir),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            close_fds=True,
        )
        assert process.stdout is not None
        assert process.stdin is not None
        output_fd = process.stdout.fileno()
        stdin_fd = process.stdin.fileno()
        os.set_blocking(output_fd, False)
        os.set_blocking(stdin_fd, False)
        return ExecSession(self._allocate_session_id(), process, output_fd, stdin_fd, command)

    def _spawn_pty(self, argv: list[str], workdir: Path, command: str) -> ExecSession:
        import pty

        master_fd, slave_fd = pty.openpty()
        process = subprocess.Popen(
            argv,
            cwd=str(workdir),
            stdin=slave_fd,
            stdout=slave_fd,
            stderr=slave_fd,
            close_fds=True,
            start_new_session=True,
        )
        os.close(slave_fd)
        os.set_blocking(master_fd, False)
        return ExecSession(self._allocate_session_id(), process, master_fd, master_fd, command)

    def _allocate_session_id(self) -> int:
        session_id = self._next_session_id
        self._next_session_id += 1
        return session_id

    def _wait_and_collect(
        self,
        session: ExecSession,
        yield_ms: int,
        max_output_tokens: int,
        remove_finished: bool,
    ) -> dict[str, Any]:
        start = time.monotonic()
        deadline = start + yield_ms / 1000
        selector = selectors.DefaultSelector()
        try:
            selector.register(session.output_fd, selectors.EVENT_READ)
            while time.monotonic() < deadline:
                timeout = max(deadline - time.monotonic(), 0)
                events = selector.select(timeout=min(timeout, 0.1))
                for key, _ in events:
                    self._read_available(session, key.fd)
                if session.process.poll() is not None:
                    self._read_available(session, session.output_fd)
                    break
        finally:
            selector.close()

        exit_code = session.process.poll()
        output = session.buffer.decode(errors="replace")
        session.buffer.clear()
        response: dict[str, Any] = {
            "wall_time_seconds": round(time.monotonic() - start, 3),
            "output": truncate_output(output, max_output_tokens),
            "original_token_count": approx_tokens(output),
        }
        if exit_code is None:
            response["session_id"] = session.session_id
        else:
            response["exit_code"] = exit_code
            if remove_finished:
                self.sessions.pop(session.session_id, None)
                self._close_session_fds(session)
        return response

    @staticmethod
    def _read_available(session: ExecSession, fd: int) -> None:
        while True:
            try:
                chunk = os.read(fd, 65536)
            except BlockingIOError:
                return
            except OSError:
                return
            if not chunk:
                return
            session.buffer.extend(chunk)

    @staticmethod
    def _close_session_fds(session: ExecSession) -> None:
        if session.process.stdout is not None:
            try:
                session.process.stdout.close()
            except OSError:
                pass
        if session.process.stdin is not None:
            try:
                session.process.stdin.close()
            except OSError:
                pass
        if session.process.stdout is None and session.process.stdin is None:
            for fd in {session.output_fd, session.stdin_fd}:
                if fd is None:
                    continue
                try:
                    os.close(fd)
                except OSError:
                    pass

    def shutdown(self) -> None:
        for session in list(self.sessions.values()):
            if session.process.poll() is None:
                try:
                    os.killpg(session.process.pid, signal.SIGTERM)
                except OSError:
                    session.process.terminate()
                try:
                    session.process.wait(timeout=1)
                except subprocess.TimeoutExpired:
                    session.process.kill()
                    session.process.wait(timeout=1)
            self._close_session_fds(session)
        self.sessions.clear()


def shell_argv(shell: str, cmd: str, login: bool) -> list[str]:
    shell_name = Path(shell).name
    if shell_name in {"bash", "zsh", "sh", "dash", "ksh"}:
        flag = "-lc" if login else "-c"
        return [shell, flag, cmd]
    if shell_name == "fish":
        return [shell, "-lc" if login else "-c", cmd]
    return [shell, "-c", cmd]


def truncate_output(output: str, max_output_tokens: int) -> str:
    max_chars = max_output_tokens * 4
    if len(output) <= max_chars:
        return output
    head = max_chars // 2
    tail = max_chars - head
    return (
        output[:head]
        + f"\n[... output truncated to {max_output_tokens} approximate tokens ...]\n"
        + output[-tail:]
    )


def approx_tokens(text: str) -> int:
    return max((len(text) + 3) // 4, 0)


def clamp_int(value: Any, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = minimum
    return max(min(parsed, maximum), minimum)


def require_string(args: dict[str, Any], key: str) -> str:
    value = args.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"{key} is required and must be a non-empty string")
    return value
