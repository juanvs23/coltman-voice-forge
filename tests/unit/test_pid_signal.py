"""pidfd handle: one identity, many signals.

Fakes only. No real signals, no real processes: ``os.pidfd_open``,
``signal.pidfd_send_signal`` and ``select.select`` are monkeypatched, and the
descriptor handed out is a real one over ``/dev/null`` so the close path is
exercised for real.
"""

from __future__ import annotations

import errno
import os
import signal

import pytest

from voiceforge.adapters.secondary import pid_signal as mod


def _real_fd() -> int:
    return os.open(os.devnull, os.O_RDONLY)


def test_one_handle_signals_twice_through_the_same_pidfd(monkeypatch):
    real_fd = _real_fd()
    opened: list[int] = []
    sent: list[tuple] = []

    def open_pidfd(pid):
        opened.append(pid)
        return real_fd

    monkeypatch.setattr(mod.os, "pidfd_open", open_pidfd)
    monkeypatch.setattr(
        mod.signal, "pidfd_send_signal", lambda fd, sig: sent.append((fd, sig))
    )

    handle = mod.open_process(4321)
    try:
        handle.signal(signal.SIGTERM)
        handle.signal(signal.SIGKILL)
    finally:
        handle.close()

    assert opened == [4321]
    assert sent == [(real_fd, signal.SIGTERM), (real_fd, signal.SIGKILL)]


def test_exited_and_wait_ask_the_descriptor_not_the_pid(monkeypatch):
    real_fd = _real_fd()
    monkeypatch.setattr(mod.os, "pidfd_open", lambda _pid: real_fd)
    probes: list[tuple] = []

    def fake_select(rlist, _wlist, _xlist, timeout):
        probes.append((rlist, timeout))
        return (rlist if len(probes) == 1 else []), [], []

    monkeypatch.setattr(mod.select, "select", fake_select)

    def forbidden(*_args):
        raise AssertionError("the pid number must never be consulted")

    monkeypatch.setattr(mod.os, "kill", forbidden)

    handle = mod.open_process(4321)
    try:
        assert handle.exited() is True
        assert handle.wait(7) is False
    finally:
        handle.close()

    assert probes == [([real_fd], 0), ([real_fd], 7)]


def test_open_process_reports_a_process_that_no_longer_exists(monkeypatch):
    def gone(_pid):
        raise ProcessLookupError(errno.ESRCH, "No such process")

    monkeypatch.setattr(mod.os, "pidfd_open", gone)

    with pytest.raises(mod.ProcessGone):
        mod.open_process(4321)


def test_signal_reports_a_process_that_died_after_the_handle_was_pinned(monkeypatch):
    real_fd = _real_fd()
    monkeypatch.setattr(mod.os, "pidfd_open", lambda _pid: real_fd)
    real_close = os.close
    closed: list[int] = []
    monkeypatch.setattr(mod.os, "close", lambda fd: closed.append(fd) or real_close(fd))

    def died(_fd, _sig):
        raise ProcessLookupError(errno.ESRCH, "No such process")

    monkeypatch.setattr(mod.signal, "pidfd_send_signal", died)

    handle = mod.open_process(4321)
    try:
        with pytest.raises(mod.ProcessGone):
            handle.signal(signal.SIGTERM)
    finally:
        handle.close()

    assert closed == [real_fd]


def test_an_unsupported_kernel_refuses_to_guess(monkeypatch):
    def no_kernel_support(_pid):
        raise OSError(errno.ENOSYS, "Function not implemented")

    monkeypatch.setattr(mod.os, "pidfd_open", no_kernel_support)

    with pytest.raises(mod.PidfdUnavailable):
        mod.open_process(4321)


def test_a_platform_without_pidfd_refuses_to_guess(monkeypatch):
    monkeypatch.delattr(mod.os, "pidfd_open", raising=False)

    with pytest.raises(mod.PidfdUnavailable):
        mod.open_process(4321)


def test_close_is_idempotent_and_releases_the_descriptor(monkeypatch):
    real_fd = _real_fd()
    real_close = os.close
    closed: list[int] = []
    monkeypatch.setattr(mod.os, "pidfd_open", lambda _pid: real_fd)
    monkeypatch.setattr(mod.os, "close", lambda fd: closed.append(fd) or real_close(fd))

    handle = mod.open_process(4321)
    handle.close()
    handle.close()

    assert closed == [real_fd]
    with pytest.raises(OSError):
        os.fstat(real_fd)


# ── ownership ───────────────────────────────────────────────────────────
def _fake_proc(tmp_path, monkeypatch, pid: int, entries: list[str]):
    """Point pid_signal at a fake /proc/<pid>/environ."""
    monkeypatch.setattr(mod, "PROC", tmp_path)
    proc_pid = tmp_path / str(pid)
    proc_pid.mkdir()
    (proc_pid / "environ").write_bytes(
        b"".join(entry.encode() + b"\0" for entry in entries)
    )


def test_identity_matches_requires_the_exact_token_entry(tmp_path, monkeypatch):
    _fake_proc(tmp_path, monkeypatch, 4321, ["PATH=/usr/bin", "VOICEFORGE_SERVER_TOKEN=abcd"])

    assert mod.identity_matches(4321, "abcd") is True


def test_identity_rejects_a_foreign_process_with_a_forged_token(tmp_path, monkeypatch):
    _fake_proc(tmp_path, monkeypatch, 4321, ["PATH=/usr/bin", "SOMEONE_ELSE=1"])

    assert mod.identity_matches(4321, "abcd") is False


def test_identity_rejects_a_prefix_of_the_real_token(tmp_path, monkeypatch):
    _fake_proc(tmp_path, monkeypatch, 4321, ["VOICEFORGE_SERVER_TOKEN=abcdef"])

    assert mod.identity_matches(4321, "abc") is False


def test_identity_is_false_when_the_process_does_not_exist(tmp_path, monkeypatch):
    monkeypatch.setattr(mod, "PROC", tmp_path)

    assert mod.identity_matches(4321, "abcd") is False


def test_identity_is_false_for_a_zombie_with_an_empty_environ(tmp_path, monkeypatch):
    _fake_proc(tmp_path, monkeypatch, 4321, [])

    assert mod.identity_matches(4321, "abcd") is False


def test_identity_refuses_when_proc_is_not_available(tmp_path, monkeypatch):
    monkeypatch.setattr(mod, "PROC", tmp_path / "missing")

    with pytest.raises(mod.PidfdUnavailable):
        mod.identity_matches(4321, "abcd")
