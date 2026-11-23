"""Admission control: one instance, one job at a time, the rest queued."""

from __future__ import annotations

import json
import threading
import time

import pytest

from voiceforge.adapters.secondary.audiocpp_server import AudiocppServerControl
from voiceforge.adapters.secondary.engine_process import EngineSupervisor
from voiceforge.adapters.secondary.fs_job_state import FileJobState
from voiceforge.application.queue import DONE, FAILED, QUEUED, RUNNING, SerialQueue
from voiceforge.domain.errors import EngineAlreadyRunning, EngineBusy, EngineUnavailable


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


TOKEN = "0f0e0d0c0b0a0908"


def _engine_pid_file(tmp_path, pid: int, token: str | None = TOKEN) -> None:
    payload = {"pid": pid, "started_at": "2026-11-23T00:00:00+00:00"}
    if token is not None:
        payload["token"] = token
    (tmp_path / "engine.pid").write_text(json.dumps(payload), encoding="utf-8")


class Handle:
    def __init__(self):
        self.signals: list[int] = []
        self.waits: list[float] = []
        self.closed = 0

    def signal(self, sig):
        self.signals.append(sig)

    def wait(self, timeout):
        self.waits.append(timeout)
        return True

    def close(self):
        self.closed += 1


def test_up_writes_the_token_and_passes_it_to_the_host(tmp_path, monkeypatch):
    from voiceforge.adapters.secondary import engine_process as engine_mod

    supervisor = _supervisor(tmp_path)
    supervisor._script.write_text("# host\n")
    captured: dict = {}

    class Process:
        pid = 4343
        returncode = None

        def poll(self):
            return None

    def popen(_args, **kwargs):
        captured.update(kwargs)
        return Process()

    monkeypatch.setattr(engine_mod.subprocess, "Popen", popen)
    monkeypatch.setattr(supervisor, "_healthy", lambda: False)
    monkeypatch.setattr(supervisor, "_lock_held", lambda: False)
    monkeypatch.setattr(engine_mod.time, "sleep", lambda _seconds: None)
    ticks = iter([0.0, 0.5, 2.0])
    monkeypatch.setattr(engine_mod.time, "monotonic", lambda: next(ticks))

    with pytest.raises(EngineUnavailable):
        supervisor.up()

    payload = json.loads(supervisor._pid_path.read_text(encoding="utf-8"))
    assert payload["pid"] == 4343
    token = payload["token"]
    assert len(token) == 16
    int(token, 16)
    assert captured["env"][engine_mod.TOKEN_ENV] == token
    assert captured["env"]["VF_LOCK_PATH"] == str(tmp_path / "engine.lock")
    assert captured["env"]["PATH"]


def test_supervisor_down_signals_the_verified_owner_once(tmp_path, monkeypatch):
    from voiceforge.adapters.secondary import engine_process as engine_mod

    supervisor = _supervisor(tmp_path)
    _engine_pid_file(tmp_path, 909)
    monkeypatch.setattr(supervisor, "_healthy", lambda: False)

    handle = Handle()
    opened: list[int] = []
    checked: list[tuple] = []

    def open_process(pid):
        opened.append(pid)
        return handle

    def identity_matches(pid, token):
        checked.append((pid, token))
        return True

    monkeypatch.setattr(engine_mod, "open_process", open_process)
    monkeypatch.setattr(engine_mod, "identity_matches", identity_matches)

    result = supervisor.down()

    assert result["pid"] == 909
    assert result["via"] == "signal"
    assert opened == [909]
    assert checked == [(909, TOKEN)]
    assert handle.signals == [engine_mod.signal.SIGTERM]
    assert handle.closed == 1
    assert not supervisor._pid_path.exists()


def test_supervisor_down_never_signals_a_foreign_pid(tmp_path, monkeypatch):
    from voiceforge.adapters.secondary import engine_process as engine_mod
    from voiceforge.domain.errors import EngineUnavailable

    supervisor = _supervisor(tmp_path)
    _engine_pid_file(tmp_path, 910, token="forged")
    monkeypatch.setattr(supervisor, "_healthy", lambda: True)
    handle = Handle()
    monkeypatch.setattr(engine_mod, "open_process", lambda pid: handle)
    monkeypatch.setattr(engine_mod, "identity_matches", lambda pid, token: False)
    monkeypatch.setattr(supervisor._http, "shutdown", lambda: None)
    monkeypatch.setattr(engine_mod.time, "sleep", lambda _seconds: None)
    ticks = iter([0.0, 0.0, 20.0])
    monkeypatch.setattr(engine_mod.time, "monotonic", lambda: next(ticks))

    with pytest.raises(EngineUnavailable) as exc:
        supervisor.down()

    assert "does not match" in str(exc.value)
    assert handle.signals == []
    assert handle.closed == 1


def test_supervisor_down_keeps_the_pid_file_when_identity_is_unknown(tmp_path, monkeypatch):
    from voiceforge.adapters.secondary import engine_process as engine_mod
    from voiceforge.domain.errors import EngineUnavailable

    supervisor = _supervisor(tmp_path)
    _engine_pid_file(tmp_path, 911)
    monkeypatch.setattr(supervisor, "_healthy", lambda: False)

    def unavailable(_pid):
        raise engine_mod.PidfdUnavailable("no pidfd support")

    monkeypatch.setattr(engine_mod, "open_process", unavailable)

    with pytest.raises(EngineUnavailable):
        supervisor.down()
    assert supervisor._pid_path.exists()


def test_supervisor_down_treats_a_legacy_pid_file_as_garbage(tmp_path, monkeypatch):
    """A pre-token plain-text pid file carries no ownership proof."""
    from voiceforge.adapters.secondary import engine_process as engine_mod

    supervisor = _supervisor(tmp_path)
    supervisor._pid_path.write_text("912", encoding="utf-8")
    monkeypatch.setattr(supervisor, "_healthy", lambda: False)
    opened: list[int] = []
    monkeypatch.setattr(engine_mod, "open_process", lambda pid: opened.append(pid))

    result = supervisor.down()

    assert result["pid"] == 912
    assert result["via"] == "garbage"
    assert opened == []
    assert not supervisor._pid_path.exists()


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
        monkeypatch.setattr(
            "voiceforge.adapters.secondary.audiocpp_server.open_process", refuse
        )

        with pytest.raises(EngineBusy):
            control.down()
    finally:
        gate.set()
    holder.wait(holder_job.id, timeout=5)
