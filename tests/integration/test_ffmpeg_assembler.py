"""Real ffmpeg run: proves the audio side without touching a model.

Evidence lives in this folder (`tests/integration/ffmpeg/evidence/`) and is
gitignored, per the shared E2E rule.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from voiceforge.adapters.secondary.ffmpeg_assembler import FfmpegAssembler

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")


def _tone(path: Path, seconds: float, frequency: int) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", f"sine=frequency={frequency}:duration={seconds}",
            "-ar", "24000", "-ac", "1", str(path),
        ],
        check=True,
    )
    return path


def test_assemble_two_lines_with_a_pause(tmp_path):
    first = _tone(tmp_path / "line-0.wav", 0.5, 440)
    second = _tone(tmp_path / "line-1.wav", 0.5, 660)
    out = tmp_path / "mix.wav"

    produced, duration = FfmpegAssembler().assemble(
        [(first, 300), (second, 0)], out, target_lufs=None
    )

    assert produced == out
    assert out.exists()
    assert 0.5 + 0.3 + 0.5 - 0.05 <= duration <= 0.5 + 0.3 + 0.5 + 0.15
    assert not (tmp_path / ".mix.parts").exists()


def test_assemble_with_loudness_mastering(tmp_path):
    first = _tone(tmp_path / "a.wav", 0.4, 500)
    out = tmp_path / "mastered.wav"

    _, duration = FfmpegAssembler().assemble([(first, 0)], out, target_lufs=-14.0)

    assert out.exists()
    assert duration >= 0.4


def test_pauses_keep_their_length_across_sample_rates(tmp_path):
    """A 24 kHz gap next to a 44.1 kHz line used to play 46 % short."""
    first = _tone(tmp_path / "a.wav", 1.0, 440)          # 24 kHz from _tone
    subprocess.run(
        ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", str(first),
         "-ar", "44100", str(tmp_path / "hi.wav")], check=True
    )
    second = _tone(tmp_path / "b.wav", 1.0, 660)
    subprocess.run(
        ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", str(second),
         "-ar", "44100", str(tmp_path / "hi2.wav")], check=True
    )

    out = tmp_path / "mix.wav"
    _, duration = FfmpegAssembler().assemble(
        [(tmp_path / "hi.wav", 500), (tmp_path / "hi2.wav", 0)], out, target_lufs=None
    )

    assert 2.45 <= duration <= 2.55, f"pause was truncated: {duration}s"


def test_mixed_rates_are_normalised_before_concatenating(tmp_path):
    a = _tone(tmp_path / "a.wav", 1.0, 440)              # 24 kHz
    b = tmp_path / "b.wav"
    subprocess.run(
        ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", str(a),
         "-ar", "22050", str(b)], check=True
    )

    out = tmp_path / "mix.wav"
    _, duration = FfmpegAssembler().assemble([(a, 300), (b, 0)], out, target_lufs=None)

    assert 2.25 <= duration <= 2.40, f"mixed rates mishandled: {duration}s"
