"""Admission control: one instance, one job at a time, the rest queued.

This is a system rule, not a model detail, so it lives in the application
layer. It uses only the standard library and knows nothing about GPUs.

Why a queue instead of parallel calls: the machine has one GPU and the host
loads one model at a time. Running two syntheses concurrently does not make
anything faster — it makes both slower and risks an out-of-memory abort.
"""

from __future__ import annotations

import os
import queue
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable

from .ports import JobState

QUEUED = "queued"
RUNNING = "running"
DONE = "done"
FAILED = "failed"


@dataclass
class Job:
    """One unit of model work, tracked from submission to result."""

    id: str
    kind: str
    state: str = QUEUED
    submitted_at: float = field(default_factory=time.time)
    started_at: float | None = None
    finished_at: float | None = None
    result: Any = None
    error: str | None = None

    def as_dict(self) -> dict:
        return {
            "id": self.id,
            "kind": self.kind,
            "state": self.state,
            "submitted_at": self.submitted_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "error": self.error,
        }


class SerialQueue:
    """FIFO with a single worker. The queue *is* the concurrency policy."""

    def __init__(self, max_pending: int = 32, state: JobState | None = None) -> None:
        self._max_pending = max_pending
        self._state = state
        self._queue: queue.Queue[str] = queue.Queue()
        self._jobs: dict[str, Job] = {}
        self._tasks: dict[str, Callable[[], Any]] = {}
        self._lock = threading.Lock()
        self._current: str | None = None
        self._closed = False
        self._worker = threading.Thread(target=self._loop, name="voice-forge-worker", daemon=True)
        self._worker.start()

    # ── public ───────────────────────────────────────────────────────────
    def submit(self, kind: str, task: Callable[[], Any]) -> Job:
        with self._lock:
            if self._closed:
                raise RuntimeError("the queue is closed")
            pending = sum(1 for job in self._jobs.values() if job.state in {QUEUED, RUNNING})
            if pending >= self._max_pending:
                raise RuntimeError(
                    f"queue is full ({pending} pending); wait for a job to finish"
                )
            job = Job(id=uuid.uuid4().hex[:12], kind=kind)
            self._jobs[job.id] = job
            self._tasks[job.id] = task
        self._queue.put(job.id)
        return job

    def wait(self, job_id: str, timeout: float | None = None) -> Job:
        deadline = None if timeout is None else time.monotonic() + timeout
        while True:
            job = self.get(job_id)
            if job.state in {DONE, FAILED}:
                return job
            if deadline is not None and time.monotonic() > deadline:
                return job
            time.sleep(0.05)

    def get(self, job_id: str) -> Job:
        with self._lock:
            return self._jobs[job_id]

    def busy(self) -> bool:
        """True while this process or any other one is running a job."""
        if self._current is not None:
            return True
        return self._state is not None and self._state.current() is not None

    def snapshot(self) -> dict:
        # The shared state is read outside the local lock: it is file I/O and
        # it must stay visible to a reader even when this queue is idle.
        active = self._state.current() if self._state is not None else None
        with self._lock:
            jobs = list(self._jobs.values())
            pending = [job for job in jobs if job.state == QUEUED]
            return {
                "busy": self._current is not None or active is not None,
                "running": self._current,
                "active": active,
                "pending": len(pending),
                "queued": [job.id for job in pending],
                "history": [job.as_dict() for job in jobs[-20:]],
            }

    def close(self) -> None:
        with self._lock:
            self._closed = True
        self._queue.put("__stop__")

    # ── worker ───────────────────────────────────────────────────────────
    def _loop(self) -> None:
        while True:
            job_id = self._queue.get()
            if job_id == "__stop__":
                return
            with self._lock:
                job = self._jobs[job_id]
                task = self._tasks.pop(job_id, None)
                if task is None:
                    continue
                job.state = RUNNING
                job.started_at = time.time()
                self._current = job_id
            try:
                if self._state is not None:
                    # Announce the job for every other process before it starts.
                    self._state.begin(job.kind, job.id, os.getpid())
                job.result = task()
                job.state = DONE
            except Exception as exc:  # noqa: BLE001 - the caller needs the reason
                job.error = f"{type(exc).__name__}: {exc}"
                job.state = FAILED
            finally:
                if self._state is not None:
                    self._state.end()
                job.finished_at = time.time()
                with self._lock:
                    self._current = None
