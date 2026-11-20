"""Process supervisor for the model host (the "on / warm / off" switches).

The host runs in its own virtualenv because it needs torch. This supervisor
only knows how to spawn it, wait for it to answer, and stop it. It never
imports it.
"""

from __future__ import annotations

import os
import signal
import subprocess
import time
from pathlib import Path
from typing import Mapping, Sequence

from ...domain.errors import EngineUnavailable
from .engine_http import HttpEngine


class EngineSupervisor:
    def __init__(
        self,
        *,
        python_exe: str,
        script: Path,
        base_url: str,
        log_path: Path,
        pid_path: Path,
        boot_timeout_s: float = 180.0,
        env: Mapping[str, str] | None = None,
    ) -> None:
        self._python = python_exe
        self._script = Path(script)
        self._base_url = base_url.rstrip("/")
        self._log_path = Path(log_path)
        self._pid_path = Path(pid_path)
        self._boot_timeout = boot_timeout_s
        self._env = dict(env or {})
        self._http = HttpEngine(base_url, timeout_s=900.0)

    # ── lifecycle ──────────────────────────────────────────────────────
    def up(self) -> Mapping[str, object]:
        if self._healthy():
            return {"status": "already-up", "pid": self._read_pid(), "url": self._base_url}

        if not self._script.exists():
            raise EngineUnavailable(f"model host script not found: {self._script}")

        self._log_path.parent.mkdir(parents=True, exist_ok=True)
        log = open(self._log_path, "ab")
        process = subprocess.Popen(  # noqa: S603 - fixed local command
            [self._python, str(self._script), "--port", self._port()],
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
            env={**os.environ, **self._env},
        )
        self._pid_path.parent.mkdir(parents=True, exist_ok=True)
        self._pid_path.write_text(str(process.pid), encoding="utf-8")

        deadline = time.monotonic() + self._boot_timeout
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise EngineUnavailable(
                    f"model host exited with code {process.returncode}; see {self._log_path}"
                )
            if self._healthy():
                return {"status": "up", "pid": process.pid, "url": self._base_url}
            time.sleep(1.0)
        raise EngineUnavailable(
            f"model host did not answer within {self._boot_timeout:.0f}s; see {self._log_path}"
        )

    def warm(self, modes: Sequence[str] | None = None) -> Mapping[str, object]:
        if not self._healthy():
            raise EngineUnavailable("model host is down; run `voice-forge up` first")
        return self._http.warm(modes)

    def status(self) -> Mapping[str, object]:
        if not self._healthy():
            return {"status": "down", "url": self._base_url}
        data = dict(self._http.health())
        data.setdefault("status", "up")
        data["url"] = self._base_url
        return data

    def down(self) -> Mapping[str, object]:
        result: dict[str, object] = {"status": "down"}
        if self._healthy():
            try:
                self._http.shutdown()
            except EngineUnavailable:
                pass
        pid = self._read_pid()
        if pid:
            try:
                os.killpg(os.getpgid(pid), signal.SIGTERM)
            except (ProcessLookupError, PermissionError):
                pass
            for _ in range(30):
                if not _alive(pid):
                    break
                time.sleep(0.5)
            if _alive(pid):
                try:
                    os.killpg(os.getpgid(pid), signal.SIGKILL)
                except (ProcessLookupError, PermissionError):
                    pass
            self._pid_path.unlink(missing_ok=True)
            result["pid"] = pid
        return result

    # ── internals ──────────────────────────────────────────────────────
    def _healthy(self) -> bool:
        try:
            self._http.health()
        except EngineUnavailable:
            return False
        return True

    def _read_pid(self) -> int | None:
        try:
            return int(self._pid_path.read_text(encoding="utf-8").strip())
        except (FileNotFoundError, ValueError):
            return None

    def _port(self) -> str:
        return self._base_url.rsplit(":", 1)[-1]


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except (ProcessLookupError, PermissionError):
        return False
    return True
