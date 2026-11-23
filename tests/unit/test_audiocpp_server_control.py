"""audio.cpp server control: pid bookkeeping, ownership, targeted shutdown.

Fakes only. No real signals, no real servers, no GPU.
"""

from __future__ import annotations

import json

import pytest

from voiceforge.adapters.secondary import audiocpp_server as mod
from voiceforge.domain.errors import EngineBusy, EngineUnavailable

TOKEN = "a1b2c3d4e5f60718"


class FakeProcess:
    pid = 4242
    returncode = None

    def poll(self):
        return None


class FakeResponse:
    def __init__(self, status_code: int = 200) -> None:
        self.status_code = status_code


class FakeClient:
    """Stands in for httpx.Client so no request leaves the test."""

    def __init__(self, *args, status: int = 200, **kwargs) -> None:
        self.posts: list[str] = []
        self.status = status

    def post(self, url, json=None):
        self.posts.append(url)
        return FakeResponse(self.status)

    def close(self) -> None:
        pass


class Health:
    """Answers the scripted health checks, repeating the last answer."""

    def __init__(self, *answers: bool) -> None:
        self._answers = list(answers)
        self.calls = 0

    def __call__(self) -> bool:
        self.calls += 1
        return self._answers.pop(0) if len(self._answers) > 1 else self._answers[0]


class FakeHandle:
    """Stands in for a pinned process: records signals and waits."""

    def __init__(self, *, wait_results=(True,), term_gone: bool = False):
        self.signals: list[int] = []
        self.waits: list[float] = []
        self.close_calls = 0
        self._wait_results = list(wait_results)
        self._term_gone = term_gone

    def signal(self, sig):
        if sig == mod.signal.SIGTERM and self._term_gone:
            raise mod.ProcessGone("gone before the signal was sent")
        self.signals.append(sig)

    def wait(self, timeout):
        self.waits.append(timeout)
        return self._wait_results.pop(0) if self._wait_results else True

    def close(self):
        self.close_calls += 1


def _control(tmp_path, *, busy=lambda: False, healthy=False):
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
    control._healthy = healthy if callable(healthy) else (lambda: healthy)
    return control


def _pid_file(tmp_path, pid: int, token: str | None = TOKEN) -> None:
    payload: dict[str, object] = {
        "pid": pid,
        "port": 8731,
        "started_at": "2026-11-23T00:00:00+00:00",
    }
    if token is not None:
        payload["token"] = token
    (tmp_path / "server.pid").write_text(json.dumps(payload), encoding="utf-8")


def _install_handle(monkeypatch, handle, *, matched: bool = True):
    opened: list[int] = []
    checked: list[tuple] = []

    def open_process(pid):
        opened.append(pid)
        return handle

    def identity_matches(pid, token):
        checked.append((pid, token))
        return matched

    monkeypatch.setattr(mod, "open_process", open_process)
    monkeypatch.setattr(mod, "identity_matches", identity_matches)
    return opened, checked


# ── up ──────────────────────────────────────────────────────────────────
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
    assert payload["token"]


def test_up_passes_the_boot_token_to_the_server(tmp_path, monkeypatch):
    control = _control(tmp_path)
    control._binary.write_text("#!/bin/sh\n")
    captured: dict = {}

    def popen(_args, **kwargs):
        captured.update(kwargs)
        return FakeProcess()

    monkeypatch.setattr(mod.subprocess, "Popen", popen)
    monkeypatch.setattr(control, "_healthy", lambda: False)
    monkeypatch.setattr(mod.time, "sleep", lambda _seconds: None)
    ticks = iter([0.0, 0.5, 2.0])
    monkeypatch.setattr(mod.time, "monotonic", lambda: next(ticks))

    with pytest.raises(EngineUnavailable):
        control.up()

    payload = json.loads((tmp_path / "server.pid").read_text(encoding="utf-8"))
    token = payload["token"]
    assert len(token) == 16
    int(token, 16)  # hex
    assert captured["env"][mod.TOKEN_ENV] == token
    assert captured["env"]["PATH"], "the inherited environment must survive"


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


# ── down: admission ─────────────────────────────────────────────────────
def test_down_refuses_while_a_job_is_running(tmp_path, monkeypatch):
    control = _control(tmp_path, busy=lambda: True)
    opened: list[int] = []
    monkeypatch.setattr(mod, "open_process", lambda pid: opened.append(pid))

    with pytest.raises(EngineBusy):
        control.down()

    assert opened == []


def test_down_force_ignores_busy(tmp_path, monkeypatch):
    control = _control(tmp_path, busy=lambda: True)
    monkeypatch.setattr(mod.httpx, "Client", FakeClient)

    assert control.down(force=True)["status"] == "down"


# ── down: the port we own ───────────────────────────────────────────────
def test_down_stops_an_answering_server_over_http_without_signals(tmp_path, monkeypatch):
    """The port is ours: /shutdown plus a quiet /health needs no pidfd."""
    health = Health(True, False, False)
    control = _control(tmp_path, healthy=health)
    _pid_file(tmp_path, 777)
    client = FakeClient()
    monkeypatch.setattr(mod.httpx, "Client", lambda *args, **kwargs: client)

    opened, _checked = _install_handle(monkeypatch, FakeHandle())
    monkeypatch.setattr(mod.time, "sleep", lambda _seconds: None)
    ticks = iter([0.0, 0.0])
    monkeypatch.setattr(mod.time, "monotonic", lambda: next(ticks))

    result = control.down()

    assert result == {"status": "down", "via": "http", "pid": 777}
    assert client.posts == ["http://127.0.0.1:8731/shutdown"]
    assert opened == []
    assert not control._pid_path.exists()


def test_down_does_not_wait_for_a_shutdown_endpoint_that_does_not_exist(tmp_path, monkeypatch):
    """audio.cpp answers 404 on /shutdown: no five seconds of silence to wait for."""
    health = Health(True)
    control = _control(tmp_path, healthy=health)
    _pid_file(tmp_path, 777)
    monkeypatch.setattr(mod.httpx, "Client", lambda *args, **kwargs: FakeClient(status=404))
    handle = FakeHandle()
    _install_handle(monkeypatch, handle)
    sleeps: list[float] = []
    monkeypatch.setattr(mod.time, "sleep", lambda seconds: sleeps.append(seconds))

    result = control.down()

    assert result["via"] == "signal"
    assert sleeps == []
    assert handle.signals  # TERM went through the verified handle


# ── down: ownership ─────────────────────────────────────────────────────
def test_down_never_signals_a_live_process_whose_token_does_not_match(tmp_path, monkeypatch):
    """Regression: a live pid that is not ours used to be killed here."""
    control = _control(tmp_path)
    _pid_file(tmp_path, 777, token="forged")
    handle = FakeHandle()
    opened, checked = _install_handle(monkeypatch, handle, matched=False)

    def forbidden(*_args):
        raise AssertionError("down must never ask the kernel about a bare pid")

    monkeypatch.setattr(mod.os, "kill", forbidden)

    result = control.down()

    assert result == {"status": "down", "via": "garbage"}
    assert opened == [777]
    assert checked == [(777, "forged")]
    assert handle.signals == []
    assert handle.close_calls == 1
    assert not control._pid_path.exists()
    assert not hasattr(mod, "_alive")


def test_down_refuses_a_foreign_pid_when_the_server_keeps_answering(tmp_path, monkeypatch):
    control = _control(tmp_path, healthy=Health(True, True, True))
    _pid_file(tmp_path, 777, token="forged")
    handle = FakeHandle()
    _install_handle(monkeypatch, handle, matched=False)
    monkeypatch.setattr(mod.httpx, "Client", FakeClient)
    monkeypatch.setattr(mod.time, "sleep", lambda _seconds: None)
    ticks = iter([0.0, 0.0, 20.0])
    monkeypatch.setattr(mod.time, "monotonic", lambda: next(ticks))

    with pytest.raises(EngineUnavailable) as exc:
        control.down()

    assert "does not match" in str(exc.value)
    assert handle.signals == []
    assert not control._pid_path.exists()


def test_down_refuses_a_pid_file_without_a_token_while_the_server_answers(tmp_path, monkeypatch):
    control = _control(tmp_path, healthy=Health(True, True, True))
    _pid_file(tmp_path, 555, token=None)
    opened: list[int] = []
    monkeypatch.setattr(mod, "open_process", lambda pid: opened.append(pid))
    monkeypatch.setattr(mod.httpx, "Client", FakeClient)
    monkeypatch.setattr(mod.time, "sleep", lambda _seconds: None)
    ticks = iter([0.0, 0.0, 20.0])
    monkeypatch.setattr(mod.time, "monotonic", lambda: next(ticks))

    with pytest.raises(EngineUnavailable) as exc:
        control.down()

    assert "no identity token" in str(exc.value)
    assert opened == []
    assert control._pid_path.exists()


def test_down_signals_the_verified_owner(tmp_path, monkeypatch):
    control = _control(tmp_path)
    _pid_file(tmp_path, 777)
    handle = FakeHandle()
    opened, checked = _install_handle(monkeypatch, handle)

    def forbidden(*args, **kwargs):
        raise AssertionError("down must never shell out to kill by name")

    monkeypatch.setattr(mod.subprocess, "run", forbidden)

    result = control.down()

    assert result == {"status": "down", "pid": 777, "via": "signal"}
    assert opened == [777]
    assert checked == [(777, TOKEN)]
    assert handle.signals == [mod.signal.SIGTERM]
    assert handle.close_calls == 1
    assert not control._pid_path.exists()


def test_down_escalates_on_the_same_handle_never_a_second_pidfd(tmp_path, monkeypatch):
    control = _control(tmp_path)
    _pid_file(tmp_path, 888)
    handle = FakeHandle(wait_results=(False, True))
    opened, _checked = _install_handle(monkeypatch, handle)

    control.down()

    assert opened == [888]
    assert handle.signals == [mod.signal.SIGTERM, mod.signal.SIGKILL]
    assert handle.waits == [15, 5]
    assert handle.close_calls == 1


def test_down_treats_a_stale_pid_file_as_garbage(tmp_path, monkeypatch):
    """Nothing holds the recorded pid: the file is junk, not a target."""
    control = _control(tmp_path)
    _pid_file(tmp_path, 999)

    def gone(_pid):
        raise mod.ProcessGone("pid 999 no longer exists")

    monkeypatch.setattr(mod, "open_process", gone)

    assert control.down() == {"status": "down", "pid": 999, "via": "garbage"}
    assert not control._pid_path.exists()


def test_down_handles_a_process_dying_after_the_handle_was_pinned(tmp_path, monkeypatch):
    control = _control(tmp_path)
    _pid_file(tmp_path, 321)
    handle = FakeHandle(term_gone=True)
    _install_handle(monkeypatch, handle)

    assert control.down() == {"status": "down", "pid": 321, "via": "signal"}
    assert handle.signals == []
    assert handle.close_calls == 1
    assert not control._pid_path.exists()


def test_down_refuses_when_identity_cannot_be_pinned(tmp_path, monkeypatch):
    """No identity, no kill: the file stays so a human can decide."""
    control = _control(tmp_path)
    _pid_file(tmp_path, 555)

    def unavailable(_pid):
        raise mod.PidfdUnavailable("no pidfd support")

    monkeypatch.setattr(mod, "open_process", unavailable)

    with pytest.raises(EngineUnavailable) as exc:
        control.down()

    assert "cannot verify the recorded pid" in str(exc.value)
    assert control._pid_path.exists()


def test_down_refuses_when_ownership_cannot_be_read(tmp_path, monkeypatch):
    control = _control(tmp_path)
    _pid_file(tmp_path, 555)
    handle = FakeHandle()

    def unavailable(_pid, _token):
        raise mod.PidfdUnavailable("no /proc")

    monkeypatch.setattr(mod, "open_process", lambda pid: handle)
    monkeypatch.setattr(mod, "identity_matches", unavailable)

    with pytest.raises(EngineUnavailable):
        control.down()

    assert handle.signals == []
    assert handle.close_calls == 1
    assert control._pid_path.exists()


def test_write_pid_leaves_no_tmp_file_behind(tmp_path):
    control = _control(tmp_path)

    control._write_pid(4321, TOKEN)

    payload = json.loads(control._pid_path.read_text(encoding="utf-8"))
    assert payload["pid"] == 4321
    assert payload["token"] == TOKEN
    leftovers = sorted(p.name for p in tmp_path.iterdir() if p.name.startswith("server.pid"))
    assert leftovers == ["server.pid"]


def test_down_refuses_an_alive_server_without_a_pid_file(tmp_path, monkeypatch):
    control = _control(tmp_path, healthy=True)
    monkeypatch.setattr(mod.httpx, "Client", FakeClient)
    monkeypatch.setattr(mod.time, "sleep", lambda _seconds: None)
    ticks = iter([0.0, 0.0, 20.0])
    monkeypatch.setattr(mod.time, "monotonic", lambda: next(ticks))
    opened: list[int] = []
    monkeypatch.setattr(mod, "open_process", lambda pid: opened.append(pid))

    with pytest.raises(EngineUnavailable) as exc:
        control.down()

    assert "pid is unknown" in str(exc.value)
    assert opened == []
