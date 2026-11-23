"""Process supervisor for the model host: one instance, up / warm / down.

Two rules are enforced here, because they are about the machine, not about a
model:

* **No second instance.** Starting a host that is already alive is an error,
  not a no-op. The host itself also takes an OS lock, so two CLIs racing
  cannot both succeed.
* **No killing work in flight.** ``down`` refuses while a job is running
  unless it is forced.
* **No killing a stranger.** The pid file records the boot token placed in the
  host's environment; ``down`` signals only after the pidfd pins the process and
  that token proves it is ours (see ``pid_signal``).
"""

from __future__ import annotations

import json
import os
import secrets
import signal
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Mapping, Sequence

from ...domain.errors import EngineAlreadyRunning, EngineBusy, EngineUnavailable
from .engine_http import HttpEngine
from .pid_signal import (
    TOKEN_ENV,
    PidfdUnavailable,
    ProcessGone,
    identity_matches,
    open_process,
)


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
        token = secrets.token_hex(8)
        process = subprocess.Popen(  # noqa: S603 - fixed local command
            [self._python, str(self._script), "--port", self._port()],
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
            env={
                **os.environ,
                **self._env,
                "VF_LOCK_PATH": str(self._lock_path),
                TOKEN_ENV: token,
            },
        )
        self._write_pid(process.pid, token)

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
        pid, token = self._read_pid()
        healthy = self._healthy()
        if healthy:
            try:
                self._http.shutdown()
            except EngineUnavailable:
                pass
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                if not self._healthy():
                    break
                time.sleep(0.25)
            if not self._healthy():
                self._pid_path.unlink(missing_ok=True)
                result["via"] = "http"
                if pid is not None:
                    result["pid"] = pid
                return result
        if pid is None:
            if healthy:
                raise EngineUnavailable(
                    "the model host is running but its pid is unknown; stop it manually"
                )
            return result
        result["pid"] = pid
        if not token:
            if healthy:
                raise EngineUnavailable(
                    "the pid file has no identity token; stop it manually"
                )
            self._pid_path.unlink(missing_ok=True)
            result["via"] = "garbage"
            return result
        try:
            handle = open_process(pid)
        except ProcessGone:
            # The file outlived the host: garbage, nothing to signal.
            self._pid_path.unlink(missing_ok=True)
            result["via"] = "garbage"
            return result
        except PidfdUnavailable as exc:
            # No identity, no kill; keep the file so the operator can decide.
            raise EngineUnavailable(
                "cannot verify the recorded pid belongs to this model host; "
                "stop it manually"
            ) from exc
        try:
            if not identity_matches(pid, token):
                # Opened first, then read: a recycled pid answers with the
                # impostor's environment and is rejected before any signal.
                self._pid_path.unlink(missing_ok=True)
                if healthy:
                    raise EngineUnavailable(
                        "a model host is running but its pid file does not match it; "
                        "stop it manually"
                    )
                result["via"] = "garbage"
                return result
            try:
                handle.signal(signal.SIGTERM)
            except ProcessGone:
                pass
            if not handle.wait(15):
                try:
                    # Same handle: never re-derive the pid for the escalation.
                    handle.signal(signal.SIGKILL)
                except ProcessGone:
                    pass
                handle.wait(5)
        except PidfdUnavailable as exc:
            raise EngineUnavailable(
                "cannot verify the recorded pid belongs to this model host; "
                "stop it manually"
            ) from exc
        finally:
            handle.close()
        self._pid_path.unlink(missing_ok=True)
        result["via"] = "signal"
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

    def _read_pid(self) -> tuple[int | None, str | None]:
        try:
            text = self._pid_path.read_text(encoding="utf-8").strip()
        except FileNotFoundError:
            return None, None
        try:
            data = json.loads(text)
        except ValueError:
            return None, None
        if isinstance(data, int):
            # A plain-text pid file from before tokens existed: the pid is still
            # readable, but it carries no ownership proof.
            return data, None
        if not isinstance(data, dict):
            return None, None
        pid = data.get("pid")
        token = data.get("token")
        return (
            pid if isinstance(pid, int) else None,
            token if isinstance(token, str) else None,
        )

    def _write_pid(self, pid: int, token: str) -> None:
        """Persist pid + boot token atomically, like the audio.cpp server does."""
        self._pid_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "pid": pid,
            "token": token,
            "started_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        }
        tmp = self._pid_path.with_name(self._pid_path.name + ".tmp")
        tmp.write_text(json.dumps(payload), encoding="utf-8")
        os.replace(tmp, self._pid_path)

    def _port(self) -> str:
        return self._base_url.rsplit(":", 1)[-1]
