"""ffmpeg adapter: join rendered lines and optionally master for delivery.

YouTube normalises to about -14 LUFS; without mastering, an emotionally
dynamic read either flattens or pumps once it is normalised upstream.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Sequence

from ...domain.errors import RenderFailed


class FfmpegAssembler:
    def __init__(self, ffmpeg: str = "ffmpeg", ffprobe: str = "ffprobe") -> None:
        self._ffmpeg = ffmpeg
        self._ffprobe = ffprobe

    def assemble(
        self,
        segments: Sequence[tuple[Path, int]],
        out_path: Path,
        target_lufs: float | None,
    ) -> tuple[Path, float]:
        if not segments:
            raise RenderFailed("nothing to assemble")

        out_path = Path(out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        workdir = out_path.parent / f".{out_path.stem}.parts"
        workdir.mkdir(parents=True, exist_ok=True)

        # Every segment must share one sample rate before concatenating: the
        # demuxer does not resample, so a 24 kHz gap next to a 44.1 kHz line
        # played 46 % short, silently. Different engines (44.1k TTS, 22.05k
        # voice conversion) make this mandatory, not defensive.
        target_rate = self._rate(Path(segments[0][0])) or 44_100

        parts: list[Path] = []
        for index, (line_path, pause_ms) in enumerate(segments):
            parts.append(self._normalise(Path(line_path), target_rate, workdir, index))
            if pause_ms > 0 and index < len(segments) - 1:
                silence = workdir / f"gap-{index:04d}.wav"
                if not silence.exists():
                    self._run(
                        [
                            self._ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
                            "-f", "lavfi", "-i",
                            f"anullsrc=channel_layout=mono:sample_rate={target_rate}",
                            "-t", f"{pause_ms / 1000:.3f}", str(silence),
                        ],
                        "could not synthesise a pause",
                    )
                parts.append(silence)

        list_file = workdir / "concat.txt"
        list_file.write_text(
            "\n".join(f"file '{part.resolve().as_posix()}'" for part in parts) + "\n",
            encoding="utf-8",
        )

        command = [
            self._ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
            "-f", "concat", "-safe", "0", "-i", str(list_file),
        ]
        if target_lufs is not None:
            command += [
                "-af", f"loudnorm=I={target_lufs}:TP=-1.5:LRA=11",
                "-ar", "48000",
            ]
        command.append(str(out_path))
        self._run(command, "could not assemble the dialogue")

        duration = self._duration(out_path)
        parts_dir_cleanup(workdir)
        return out_path, duration

    # ── internals ──────────────────────────────────────────────────────
    def _normalise(self, path: Path, rate: int, workdir: Path, index: int) -> Path:
        if self._rate(path) == rate:
            return path
        out = workdir / f"norm-{index:04d}.wav"
        self._run(
            [
                self._ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
                "-i", str(path), "-ac", "1", "-ar", str(rate), str(out),
            ],
            f"could not normalise {path.name} to {rate} Hz",
        )
        return out

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

    def _run(self, command: list[str], message: str) -> None:
        result = subprocess.run(  # noqa: S603 - fixed local command
            command, capture_output=True, text=True, check=False
        )
        if result.returncode != 0:
            raise RenderFailed(f"{message}: {result.stderr.strip()[:400]}")

    def _duration(self, path: Path) -> float:
        result = subprocess.run(  # noqa: S603
            [
                self._ffprobe, "-v", "error", "-show_entries", "format=duration",
                "-of", "json", str(path),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            return 0.0
        try:
            return float(json.loads(result.stdout)["format"]["duration"])
        except (KeyError, ValueError, json.JSONDecodeError):
            return 0.0


def parts_dir_cleanup(directory: Path) -> None:
    for child in directory.glob("*"):
        child.unlink(missing_ok=True)
    directory.rmdir()
