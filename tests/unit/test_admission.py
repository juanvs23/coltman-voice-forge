"""Admission control: one instance, one job at a time, the rest queued."""

from __future__ import annotations

import threading
import time

import pytest

from voiceforge.adapters.secondary.audiocpp_server import AudiocppServerControl
from voiceforge.adapters.secondary.engine_process import EngineSupervisor
from voiceforge.adapters.secondary.fs_job_state import FileJobState
from voiceforge.application.queue import DONE, FAILED, QUEUED, RUNNING, SerialQueue
from voiceforge.domain.errors import EngineAlreadyRunning, EngineBusy


def test_queue_runs_one_at_a_time_in_order():
    queue = SerialQueue()
    order: list[str] = []
    gate = threading.Event()

    first = queue.submit("a", lambda: (order.append("a"), gate.wait(2), "A")[-1])
    second = queue.submit("b", lambda: (order.append("b"), "B")[-1])

    time.sleep(0.15)
    snapshot = queue.snapshot()
    assert snapshot["busy"] is True
    assert snapshot["running"] == first.id
    assert snapshot["pending"] == 1

    gate.set()
    queue.wait(first.id, timeout=5)
    queue.wait(second.id, timeout=5)
    assert order == ["a", "b"]
    assert queue.get(first.id).state == DONE
    assert queue.get(second.id).state == DONE


def test_queue_reports_failures_without_killing_the_worker():
    queue = SerialQueue()

    def boom():
        raise ValueError("nope")

    failing = queue.submit("boom", boom)
    queue.wait(failing.id, timeout=5)
    assert queue.get(failing.id).state == FAILED
    assert "nope" in queue.get(failing.id).error

    ok = queue.submit("ok", lambda: 42)
    queue.wait(ok.id, timeout=5)
    assert queue.get(ok.id).state == DONE
    assert queue.get(ok.id).result == 42


def test_queue_is_bounded():
    queue = SerialQueue(max_pending=1)
    gate = threading.Event()
    queue.submit("a", lambda: gate.wait(2))
    time.sleep(0.05)
    with pytest.raises(RuntimeError):
        queue.submit("b", lambda: None)
    gate.set()


# ── supervisor ──────────────────────────────────────────────────────────
def _supervisor(tmp_path, busy=lambda: False):
    return EngineSupervisor(
        python_exe="/usr/bin/false",
        script=tmp_path / "host.py",
        base_url="http://127.0.0.1:9",
        log_path=tmp_path / "engine.log",
        pid_path=tmp_path / "engine.pid",
        lock_path=tmp_path / "engine.lock",
        busy=busy,
        boot_timeout_s=1,
    )


def test_up_refuses_a_second_instance(tmp_path, monkeypatch):
    supervisor = _supervisor(tmp_path)
    monkeypatch.setattr(supervisor, "_healthy", lambda: True)

    with pytest.raises(EngineAlreadyRunning):
        supervisor.up()


def test_down_refuses_while_a_job_is_running(tmp_path, monkeypatch):
    supervisor = _supervisor(tmp_path, busy=lambda: True)
    monkeypatch.setattr(supervisor, "_healthy", lambda: True)

    with pytest.raises(EngineBusy):
        supervisor.down()


def test_down_force_ignores_busy(tmp_path, monkeypatch):
    supervisor = _supervisor(tmp_path, busy=lambda: True)
    monkeypatch.setattr(supervisor, "_healthy", lambda: False)

    assert supervisor.down(force=True)["status"] == "down"


# ── admission crosses processes ────────────────────────────────────────
def test_down_refuses_a_job_running_in_another_queue_instance(tmp_path, monkeypatch):
    """The job lives in a different queue (different descriptors, same files)."""
    gate = threading.Event()
    entered = threading.Event()
    holder = SerialQueue(state=FileJobState(tmp_path))
    holder_job = holder.submit("render", lambda: (entered.set(), gate.wait(5), "ok")[-1])
    try:
        assert entered.wait(2), "the first queue never started its job"

        foreign = SerialQueue(state=FileJobState(tmp_path))
        control = AudiocppServerControl(
            tmp_path / "audiocpp_server",
            tmp_path / "model.gguf",
            backend="cpu",
            port=8731,
            config_path=tmp_path / "server.json",
            log_path=tmp_path / "server.log",
            pid_path=tmp_path / "server.pid",
            busy=lambda: foreign.busy(),
        )
        monkeypatch.setattr(control, "_healthy", lambda: True)

        def refuse(*args, **kwargs):
            raise AssertionError("down must refuse before touching HTTP or signals")

        monkeypatch.setattr("voiceforge.adapters.secondary.audiocpp_server.httpx.Client", refuse)
        monkeypatch.setattr("voiceforge.adapters.secondary.audiocpp_server.os.killpg", refuse)

        with pytest.raises(EngineBusy):
            control.down()
    finally:
        gate.set()
    holder.wait(holder_job.id, timeout=5)
