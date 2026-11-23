"""Voice conversion with tone-color-vc: borrow another voice's timbre.

The runtime runs one conversion per process (``--task vc``); the model is not
kept resident, so this adapter is deliberately separate from the TTS pair. The
source clip supplies the performance (timing, emphasis, emotion); the target
reference supplies only the timbre.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Mapping, Sequence

from ...domain.errors import RenderFailed

TASK = "vc"
FAMILY = "tone_color_vc"


class AudiocppTimbre:
    """Implements ``TimbreTransformer`` over the audio.cpp CLI."""

    def __init__(
        self,
        binary: Path,
        model: Path,
        backend: str = "cuda",
        env: Mapping[str, str] | None = None,
        timeout_s: float = 600.0,
        runner=None,
    ) -> None:
        self.binary = Path(binary)
        self.model = Path(model)
        self.backend = backend
        self._timeout = timeout_s
        self._env = dict(env or {})
        self._run = runner or (lambda command, timeout: _run(command, timeout, self._env))

    def timbre(self, source: Path, target_ref: Path, out_path: Path) -> None:
        out_path = Path(out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)

        command = [
            str(self.binary),
            "--task", TASK,
            "--family", FAMILY,
            "--backend", self.backend,
            "--model", str(self.model),
            "--audio", str(source),
            "--voice-ref", str(target_ref),
            "--out", str(out_path),
        ]
        code, output = self._run(command, self._timeout)
        if code != 0:
            tail = " | ".join(output.strip().splitlines()[-6:])
            raise RenderFailed(f"timbre conversion failed: {tail}")
        if not out_path.exists() or out_path.stat().st_size == 0:
            raise RenderFailed("the timbre conversion produced no audio")


def _run(command: Sequence[str], timeout: float, env: Mapping[str, str] | None = None) -> tuple[int, str]:
    import os

    try:
        result = subprocess.run(  # noqa: S603 - fixed local binary
            list(command),
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
            env={**os.environ, **dict(env or {})} if env else None,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 1, str(exc)
    return result.returncode, (result.stdout or "") + (result.stderr or "")
