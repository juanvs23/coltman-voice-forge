"""Cross-process job state: flock is the truth, the json only describes it.

Two ``FileJobState`` instances over the same directory use separate descriptors,
and ``flock`` locks belong to the open file description, not to the process, so
they conflict at kernel level even inside one test process. That is why these
tests do not need a real subprocess to simulate "another process".
"""

from __future__ import annotations

import json
import threading
import time

import pytest

from voiceforge.adapters.secondary.fs_job_state import FileJobState
from voiceforge.domain.errors import EngineBusy
from voiceforge.application.queue import SerialQueue


def test_state_is_visible_from_another_instance(tmp_path):
    holder = FileJobState(tmp_path)
    holder.begin("render", "job-1", 4242)
    try:
        reader = FileJobState(tmp_path)
        current = reader.current()
        assert current is not None
        assert current["job_id"] == "job-1"
        assert current["kind"] == "render"
        assert current["pid"] == 4242
        assert current["started_at"] > 0
    finally:
        holder.end()

    reader = FileJobState(tmp_path)
    assert reader.current() is None
    assert not (tmp_path / "active-job.json").exists()


def test_orphan_json_without_a_lock_is_cleaned_up(tmp_path):
    state = FileJobState(tmp_path)
    (tmp_path / "active-job.json").write_text(
        json.dumps({"job_id": "ghost", "kind": "render", "pid": 1}),
        encoding="utf-8",
    )

    assert state.current() is None
    assert not (tmp_path / "active-job.json").exists()


def test_queue_sees_a_job_running_in_another_queue(tmp_path):
    gate = threading.Event()
    entered = threading.Event()
    holder = SerialQueue(state=FileJobState(tmp_path))
    job = holder.submit("render", lambda: (entered.set(), gate.wait(5), "ok")[-1])
    try:
        assert entered.wait(2), "the first queue never started its job"
        foreign = SerialQueue(state=FileJobState(tmp_path))
        assert foreign.busy() is True
        active = foreign.snapshot()["active"]
        assert active is not None
        assert active["kind"] == "render"
    finally:
        gate.set()
    holder.wait(job.id, timeout=5)

    # DONE is set just before the worker releases the lock; poll briefly.
    deadline = time.monotonic() + 2
    while foreign.busy() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert foreign.busy() is False


def test_end_is_idempotent_and_safe_without_begin(tmp_path):
    state = FileJobState(tmp_path)
    state.end()
    state.end()
    assert state.current() is None


def test_a_second_holder_is_refused_with_a_clear_error(tmp_path):
    first = FileJobState(tmp_path)
    first.begin("render", "job-1", 111)
    second = FileJobState(tmp_path)

    with pytest.raises(EngineBusy) as exc:
        second.begin("preview", "job-2", 222)
    assert "another process" in str(exc.value)

    first.end()
    second.begin("preview", "job-2", 222)
    assert second.current()["kind"] == "preview"
    second.end()
