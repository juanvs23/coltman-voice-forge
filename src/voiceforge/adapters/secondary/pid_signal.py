"""Signal a process by the identity the kernel pins, never by a bare pid.

Why this exists: a pid file can outlive its process (segfault, OOM, ``kill -9``)
and the kernel recycles pids. Signalling a recorded pid directly — or worse, its
process group via ``killpg`` — can therefore land on an unrelated process that
happened to inherit the number. The pid stays the same; the process behind it
does not.

A pidfd closes half of that gap: ``os.pidfd_open`` returns a descriptor bound to
the process that holds the number *at open time*, and the kernel keeps that
binding until that process exits. It proves it is still the process we opened,
not that it is **ours**. A pid recycled before ``down`` runs has a live owner,
and its pidfd happily points at the new owner — so a pidfd alone cannot tell
"our server" from "a stranger that inherited the number".

Ownership therefore needs a second fact that only our server could carry: a
random token written into its environment at ``up`` time. ``identity_matches``
checks ``/proc/<pid>/environ`` for it. A recycled pid cannot hold a token it was
never given.

The order matters, and it is why the API is a handle and not a one-shot
``signal(pid, sig)``:

1. open the pidfd (the descriptor that will carry every signal),
2. verify the token of the process the descriptor is bound to,
3. signal **through that same descriptor**.

Doing it in that order means a process that dies and is recycled between steps 1
and 2 makes the token check read the impostor's environment, which fails; a
process that dies after step 2 is still the one the fd is bound to, so the send
returns ``ProcessLookupError``. Neither window reaches a stranger.

Policy: without identity there is no kill. When the platform cannot provide a
pidfd or ``/proc``, the caller must refuse and leave the pid file alone.
"""

from __future__ import annotations

import os
import select
import signal
from pathlib import Path

TOKEN_ENV = "VOICEFORGE_SERVER_TOKEN"
PROC = Path("/proc")


class ProcessGone(Exception):
    """The process the recorded pid pointed at no longer exists."""


class PidfdUnavailable(Exception):
    """The kernel could not pin the pid's identity, so no signal is safe."""


class ProcessHandle:
    """One pinned process identity: every signal and wait uses the same pidfd."""

    def __init__(self, fd: int) -> None:
        self._fd = fd

    def signal(self, sig: int) -> None:
        """Send ``sig`` to the pinned process.

        Raises ``ProcessGone`` when it has already exited, and
        ``PidfdUnavailable`` when the kernel refuses for any other reason.
        """
        fd = self._live_fd()
        try:
            signal.pidfd_send_signal(fd, sig)
        except ProcessLookupError as exc:
            # It died between opening the pidfd and sending: the descriptor is
            # stale but still bound to that process, so no stranger is involved.
            raise ProcessGone("the pinned process died before the signal was sent") from exc
        except OSError as exc:
            raise PidfdUnavailable(f"the kernel refused the signal: {exc}") from exc

    def exited(self) -> bool:
        """True when the pinned process has exited. Never signals anything."""
        return bool(select.select([self._live_fd()], [], [], 0)[0])

    def wait(self, timeout: float) -> bool:
        """Block up to ``timeout`` seconds; True when the process has exited.

        A pidfd becomes readable on exit, and this descriptor is the identity,
        so the answer cannot be about a recycled pid the way ``os.kill(pid, 0)``
        would be.
        """
        return bool(select.select([self._live_fd()], [], [], timeout)[0])

    def close(self) -> None:
        """Release the identity. Idempotent."""
        if self._fd is None:
            return
        fd, self._fd = self._fd, None
        os.close(fd)

    def _live_fd(self) -> int:
        if self._fd is None:
            raise ValueError("the process handle is closed")
        return self._fd


def open_process(pid: int) -> ProcessHandle:
    """Pin ``pid``'s identity.

    Raises ``ProcessGone`` when nothing holds that pid, and
    ``PidfdUnavailable`` when identity cannot be established (no pidfd support,
    ``ENOSYS``, ``EINVAL``, ``EPERM`` or any other kernel refusal).
    """
    open_pidfd = getattr(os, "pidfd_open", None)
    if open_pidfd is None or getattr(signal, "pidfd_send_signal", None) is None:
        raise PidfdUnavailable("this platform has no pidfd support; refusing to signal by pid")

    try:
        return ProcessHandle(open_pidfd(pid))
    except ProcessLookupError as exc:
        raise ProcessGone(f"pid {pid} no longer exists") from exc
    except OSError as exc:
        # ENOSYS (no kernel support), EINVAL (not a valid pid) or EPERM (not our
        # process): in every case we cannot prove the identity, so we do not act.
        raise PidfdUnavailable(f"cannot pin pid {pid}: {exc}") from exc


def identity_matches(pid: int, token: str) -> bool:
    """True when the process behind ``pid`` carries exactly our boot token.

    This is the ownership half of the check: the pidfd proves the process is the
    one opened, and this proves it is the one we started. Call it **after**
    opening the handle, so the process it reads is the one the handle is bound
    to; a recycled pid was never given the token.

    ``False`` covers "no such process", "a zombie" (empty environ) and "another
    process entirely". ``PidfdUnavailable`` means the environment cannot be read
    at all (no ``/proc``, or another user's process), so identity is unknowable.
    """
    if not token:
        return False
    if not PROC.is_dir():
        raise PidfdUnavailable("no /proc on this platform; process ownership cannot be verified")
    try:
        raw = (PROC / str(pid) / "environ").read_bytes()
    except FileNotFoundError:
        return False
    except PermissionError as exc:
        raise PidfdUnavailable(f"cannot read the environment of pid {pid}: {exc}") from exc
    except OSError as exc:
        raise PidfdUnavailable(f"cannot read the environment of pid {pid}: {exc}") from exc
    if not raw:
        return False
    return f"{TOKEN_ENV}={token}".encode() in raw.split(b"\0")
