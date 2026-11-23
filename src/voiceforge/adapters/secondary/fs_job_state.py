"""Cross-process job visibility: an advisory lock plus a descriptive json.

Why this exists: every CLI invocation builds its own ``SerialQueue``, so an
in-process ``busy()`` flag is blind to work started by another process. A
render running in one terminal must make ``voice-forge down`` in another
refuse. The kernel's advisory lock on one file is that shared truth; it needs
no daemon and no IPC protocol.

Contract:

* ``begin()`` opens ``active-job.lock``, takes ``LOCK_EX | LOCK_NB`` and keeps
  the descriptor open for the whole job, then writes ``active-job.json``
  atomically. Keeping the descriptor open is what makes the lock visible to
  every other descriptor -- including other descriptors in this same process,
  because ``flock`` locks belong to the open file description, not to the
  process.
* ``end()`` removes the json, releases the lock and closes the descriptor.
  It is idempotent and does nothing when no job was ever begun by this object.
* ``current()`` probes the lock with a separate descriptor: if it can take it,
  no job is running and any json left behind is an orphan; if it cannot, the
  job is alive and the json is read back.

On platforms without ``fcntl`` the json plus ``os.kill(pid, 0)`` is the
fallback: the pid decides whether the job still lives. No extra dependency.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

from ...domain.errors import EngineBusy

try:  # POSIX only; the fallback below covers the rest.
    import fcntl
except ImportError:  # pragma: no cover - non-Linux
    fcntl = None  # type: ignore[assignment]

_UNKNOWN = {"job_id": None, "kind": "unknown", "pid": None}


class FileJobState:
    """``JobState`` backed by ``<directory>/active-job.lock`` and ``.json``."""

    def __init__(self, directory: Path) -> None:
        self._directory = Path(directory)
        self._directory.mkdir(parents=True, exist_ok=True)
        self._lock_path = self._directory / "active-job.lock"
        self._json_path = self._directory / "active-job.json"
        # Opened lazily on the first begin and closed by end: a CLI that only
        # reads the state never holds a descriptor.
        self._fd: int | None = None
        self._held = False

    # ── port ────────────────────────────────────────────────────────────
    def begin(self, kind: str, job_id: str, pid: int) -> None:
        if self._held:
            raise RuntimeError("this job state already holds the active job")
        if fcntl is None:  # pragma: no cover - non-Linux
            self._write_json(kind, job_id, pid)
            self._held = True
            return
        fd = self._ensure_fd()
        if not _lock(fd):
            # A genuine second job should never get here: the queue serialises
            # work. A reader probing with ``current()`` holds the lock for a few
            # microseconds, so retry briefly before treating it as foreign.
            for _ in range(20):
                time.sleep(0.01)
                if _lock(fd):
                    break
            else:
                self._close_fd()
                raise EngineBusy(
                    "another process is running a job; wait for it to finish"
                )
        self._held = True
        self._write_json(kind, job_id, pid)

    def end(self) -> None:
        if not self._held:
            return
        self._held = False
        self._unlink_json()
        self._close_fd()

    def current(self) -> dict | None:
        if fcntl is None:  # pragma: no cover - non-Linux
            return self._current_from_pid()
        try:
            probe = open(self._lock_path, "a+")
        except OSError:
            return None
        try:
            if not _lock(probe):
                data = self._read_json()
                return data if data is not None else dict(_UNKNOWN)
            # We took the lock: nobody is working, so any json is an orphan.
            _unlock(probe)
            self._unlink_json()
            return None
        finally:
            probe.close()

    # ── internals ───────────────────────────────────────────────────────
    def _ensure_fd(self) -> int:
        if self._fd is None:
            self._fd = os.open(self._lock_path, os.O_RDWR | os.O_CREAT, 0o644)
        return self._fd

    def _close_fd(self) -> None:
        if self._fd is not None:
            try:
                os.close(self._fd)
            finally:
                self._fd = None

    def _write_json(self, kind: str, job_id: str, pid: int) -> None:
        payload = {
            "job_id": job_id,
            "kind": kind,
            "pid": pid,
            "started_at": time.time(),
        }
        tmp = self._json_path.with_name(self._json_path.name + ".tmp")
        tmp.write_text(json.dumps(payload), encoding="utf-8")
        os.replace(tmp, self._json_path)

    def _read_json(self) -> dict | None:
        try:
            data = json.loads(self._json_path.read_text(encoding="utf-8"))
        except (FileNotFoundError, ValueError, OSError):
            return None
        return data if isinstance(data, dict) else None

    def _unlink_json(self) -> None:
        self._json_path.unlink(missing_ok=True)

    def _current_from_pid(self) -> dict | None:  # pragma: no cover - non-Linux
        data = self._read_json()
        if data is None:
            return None
        pid = data.get("pid")
        if not isinstance(pid, int):
            self._unlink_json()
            return None
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            self._unlink_json()
            return None
        except PermissionError:
            # The pid exists but belongs to someone else: still a live job.
            return data
        return data


def _lock(fd: int) -> bool:
    """Try a non-blocking exclusive lock; True when this descriptor got it."""
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        return False
    return True


def _unlock(fd: int) -> None:
    fcntl.flock(fd, fcntl.LOCK_UN)
