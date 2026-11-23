"""audio.cpp server control: pid bookkeeping and targeted shutdown.

Fakes only. No real signals, no real servers, no GPU.
"""

from __future__ import annotations

import json

import pytest

from voiceforge.adapters.secondary import audiocpp_server as mod
from voiceforge.domain.errors import EngineBusy, EngineUnavailable


class FakeProcess:
    pid = 4242
    returncode = None

    def poll(self):
        return None


class FakeClient:
    """Stands in for httpx.Client so no request leaves the test."""

    def __init__(self, *args, **kwargs) -> None:
        self.posts: list[str] = []

    def post(self, url, json=None):
        self.posts.append(url)
        return None

    def close(self) -> None:
        pass


def _control(tmp_path, *, busy=lambda: False, healthy: bool = False):
    control = mod.AudiocppServerControl(
        binary=tmp_path / "audiocpp_server",
        model=tmp_path / "model.gguf",
        config_path=tmp_path / "server.json",
        log_path=tmp_path / "server.log",
        pid_path=tmp_path / "server.pid",
        port=8731,
        busy=busy,
        boot_timeout_s=1,
    )
    control._healthy = lambda: healthy
    return control


def test_up_writes_the_pid_file(tmp_path, monkeypatch):
    control = _control(tmp_path)
    control._binary.write_text("#!/bin/sh\n")
    monkeypatch.setattr(mod.subprocess, "Popen", lambda *args, **kwargs: FakeProcess())
    monkeypatch.setattr(control, "_healthy", lambda: False)
    monkeypatch.setattr(mod.time, "sleep", lambda _seconds: None)
    ticks = iter([0.0, 0.5, 2.0])
    monkeypatch.setattr(mod.time, "monotonic", lambda: next(ticks))

    with pytest.raises(EngineUnavailable):
        control.up()

    payload = json.loads((tmp_path / "server.pid").read_text(encoding="utf-8"))
    assert payload["pid"] == 4242
    assert payload["port"] == 8731
    assert payload["started_at"]


def test_up_deletes_the_pid_file_when_the_process_dies_during_boot(tmp_path, monkeypatch):
    control = _control(tmp_path)
    control._binary.write_text("#!/bin/sh\n")

    class DeadProcess(FakeProcess):
        returncode = 1

        def poll(self):
            return 1

    monkeypatch.setattr(mod.subprocess, "Popen", lambda *args, **kwargs: DeadProcess())
    monkeypatch.setattr(control, "_healthy", lambda: False)

    with pytest.raises(EngineUnavailable):
        control.up()

    assert not (tmp_path / "server.pid").exists()


def test_down_refuses_while_a_job_is_running(tmp_path, monkeypatch):
    control = _control(tmp_path, busy=lambda: True)
    killed: list[tuple] = []
    monkeypatch.setattr(mod.os, "killpg", lambda *args: killed.append(args))

    with pytest.raises(EngineBusy):
        control.down()

    assert killed == []


def test_down_force_ignores_busy(tmp_path, monkeypatch):
    control = _control(tmp_path, busy=lambda: True)
    monkeypatch.setattr(mod.httpx, "Client", FakeClient)

    assert control.down(force=True)["status"] == "down"


def test_down_signals_only_the_pid_from_the_file(tmp_path, monkeypatch):
    control = _control(tmp_path, healthy=True)
    control._pid_path.write_text(
        json.dumps({"pid": 777, "port": 8731, "started_at": "2026-11-23T00:00:00+00:00"}),
        encoding="utf-8",
    )

    monkeypatch.setattr(mod.httpx, "Client", FakeClient)
    calls: list[tuple] = []
    monkeypatch.setattr(mod.os, "getpgid", lambda pid: calls.append(("getpgid", pid)) or pid)
    monkeypatch.setattr(
        mod.os, "killpg", lambda pgid, sig: calls.append(("killpg", pgid, sig))
    )
    alive = iter([True, False, False])
    monkeypatch.setattr(mod, "_alive", lambda pid: next(alive))
    monkeypatch.setattr(mod.time, "sleep", lambda _seconds: None)

    def forbidden(*args, **kwargs):
        raise AssertionError("down must never shell out to kill by name")

    monkeypatch.setattr(mod.subprocess, "run", forbidden)

    result = control.down()

    assert result == {"status": "down", "pid": 777}
    assert calls[0] == ("getpgid", 777)
    assert ("killpg", 777, mod.signal.SIGTERM) in calls
    assert ("killpg", 777, mod.signal.SIGKILL) not in calls
    assert not control._pid_path.exists()


def test_down_escalates_to_sigkill_when_the_process_ignores_sigterm(tmp_path, monkeypatch):
    control = _control(tmp_path)
    control._pid_path.write_text(json.dumps({"pid": 888}), encoding="utf-8")

    calls: list[tuple] = []
    monkeypatch.setattr(mod.os, "getpgid", lambda pid: pid)
    monkeypatch.setattr(
        mod.os, "killpg", lambda pgid, sig: calls.append((pgid, sig))
    )
    monkeypatch.setattr(mod, "_alive", lambda pid: True)
    monkeypatch.setattr(mod.time, "sleep", lambda _seconds: None)
    ticks = iter([0.0, 0.0, 20.0])
    monkeypatch.setattr(mod.time, "monotonic", lambda: next(ticks))

    control.down()

    assert calls == [(888, mod.signal.SIGTERM), (888, mod.signal.SIGKILL)]


def test_down_refuses_an_alive_server_without_a_pid_file(tmp_path, monkeypatch):
    control = _control(tmp_path, healthy=True)
    monkeypatch.setattr(mod.httpx, "Client", FakeClient)
    killed: list[tuple] = []
    monkeypatch.setattr(mod.os, "killpg", lambda *args: killed.append(args))

    with pytest.raises(EngineUnavailable) as exc:
        control.down()

    assert "pid is unknown" in str(exc.value)
    assert killed == []
