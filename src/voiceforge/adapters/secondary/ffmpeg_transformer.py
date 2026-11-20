"""Pitch/formant transformation with ffmpeg: derive a voice without a model.

`asetrate` shifts pitch *and* formants (which is what moves perceived age and
build); `atempo` puts the duration back. No download, fully deterministic.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from ...domain.errors import RenderFailed


class FfmpegTransformer:
    def __init__(self, ffmpeg: str = "ffmpeg", ffprobe: str = "ffprobe") -> None:
        self._ffmpeg = ffmpeg
        self._ffprobe = ffprobe

    def pitch(self, source: Path, out_path: Path, semitones: float) -> None:
        if abs(semitones) < 1e-3:
            raise RenderFailed("a pitch shift of 0 semitones would produce the same voice")

        rate = self._rate(source) or 44_100
        ratio = 2 ** (semitones / 12.0)
        # atempo accepts 0.5..2.0, which covers the -6..+6 semitone range.
        tempo = 1.0 / ratio
        filters = f"asetrate={rate}*{ratio:.6f},aresample={rate},atempo={tempo:.6f}"

        out_path.parent.mkdir(parents=True, exist_ok=True)
        result = subprocess.run(  # noqa: S603 - fixed local command
            [
                self._ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
                "-i", str(source), "-af", filters,
                "-ac", "1", "-ar", str(rate), str(out_path),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            raise RenderFailed(f"could not transform the voice: {result.stderr.strip()[:300]}")

    def _rate(self, path: Path) -> int:
        result = subprocess.run(  # noqa: S603
            [
                self._ffprobe, "-v", "error", "-select_streams", "a:0",
                "-show_entries", "stream=sample_rate", "-of", "csv=p=0", str(path),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        try:
            return int(result.stdout.strip().splitlines()[0])
        except (ValueError, IndexError):
            return 0
