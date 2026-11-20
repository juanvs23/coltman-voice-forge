"""Process supervisor for the model host: one instance, up / warm / down.

Two rules are enforced here, because they are about the machine, not about a
model:

* **No second instance.** Starting a host that is already alive is an error,
  not a no-op. The host itself also takes an OS lock, so two CLIs racing
  cannot both succeed.
* **No killing work in flight.** ``down`` refuses while a job is running
  unless it is forced.
"""

from __future__ import annotations

import os
import signal
import subprocess
import time
from pathlib import Path
from typing import Callable, Mapping, Sequence

from ...domain.errors import EngineAlreadyRunning, EngineBusy, EngineUnavailable
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
        lock_path: Path,
        busy: Callable[[], bool] | None = None,
        boot_timeout_s: float = 180.0,
        env: Mapping[str, str] | None = None,
    ) -> None:
        self._python = python_exe
        self._script = Path(script)
        self._base_url = base_url.rstrip("/")
        self._log_path = Path(log_path)
        self._pid_path = Path(pid_path)
        self._lock_path = Path(lock_path)
        self._busy = busy or (lambda: False)
        self._boot_timeout = boot_timeout_s
        self._env = dict(env or {})
        self._http = HttpEngine(base_url, timeout_s=900.0)

    # ── lifecycle ──────────────────────────────────────────────────────
    def up(self) -> Mapping[str, object]:
        if self._healthy():
            raise EngineAlreadyRunning(
                "the model host is already running; refusing a second instance. "
                "Use `voice-forge down` first."
            )
        if self._lock_held():
            raise EngineAlreadyRunning(
                "another process holds the engine lock; refusing a second instance"
            )
        if not self._script.exists():
            raise EngineUnavailable(f"model host script not found: {self._script}")

        self._log_path.parent.mkdir(parents=True, exist_ok=True)
        log = open(self._log_path, "ab")
        process = subprocess.Popen(  # noqa: S603 - fixed local command
            [self._python, str(self._script), "--port", self._port()],
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
            env={**os.environ, **self._env, "VF_LOCK_PATH": str(self._lock_path)},
        )
        self._pid_path.parent.mkdir(parents=True, exist_ok=True)
        self._pid_path.write_text(str(process.pid), encoding="utf-8")

        deadline = time.monotonic() + self._boot_timeout
        while time.monotonic() < deadline:
            if process.poll() is not None:
                if process.returncode == 3:
                    raise EngineAlreadyRunning(
                        "the host refused to start: another instance holds the lock"
                    )
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

    def down(self, *, force: bool = False) -> Mapping[str, object]:
        if self._busy() and not force:
            raise EngineBusy(
                "a job is running; wait for it or use `down --force` to discard it"
            )
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

    def _lock_held(self) -> bool:
        """True when some live process holds the host's lock file."""
        if not self._lock_path.exists():
            return False
        try:
            import fcntl

            with open(self._lock_path, "r+") as handle:
                try:
                    fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except OSError:
                    return True
                fcntl.flock(handle, fcntl.LOCK_UN)
                return False
        except OSError:
            return False

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
