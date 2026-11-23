"""The timbre adapter: exact command shape, no binary, no model, no GPU."""

from __future__ import annotations

import wave
from pathlib import Path

import pytest

from voiceforge.adapters.secondary.audiocpp_timbre import AudiocppTimbre
from voiceforge.domain.errors import RenderFailed


def _write_wav(path: Path, rate: int = 22_050) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(b"\x00\x00" * 1000)


class RecordingRunner:
    def __init__(self, code: int = 0, output: str = "", write: bool = True) -> None:
        self.commands: list[list[str]] = []
        self.timeouts: list[float] = []
        self.code = code
        self.output = output
        self.write = write

    def __call__(self, command, timeout):
        self.commands.append(list(command))
        self.timeouts.append(timeout)
        if self.write:
            out = Path(command[command.index("--out") + 1])
            _write_wav(out)
        return self.code, self.output


@pytest.fixture
def adapter(tmp_path) -> tuple[AudiocppTimbre, RecordingRunner]:
    runner = RecordingRunner()
    binary = tmp_path / "audiocpp_cli"
    binary.write_text("#!/bin/sh\n")
    model = tmp_path / "tone-color-vc-f16.gguf"
    model.write_bytes(b"gguf")
    return (
        AudiocppTimbre(
            binary,
            model,
            backend="cuda",
            env={"LD_LIBRARY_PATH": "/dist/cuda/usr/lib64"},
            timeout_s=42,
            runner=runner,
        ),
        runner,
    )


def test_the_conversion_is_one_vc_process_with_the_documented_flags(
    adapter, tmp_path
):
    converter, runner = adapter
    source = tmp_path / "catalog/alex/ref.wav"
    target = tmp_path / "catalog/narrador-terror/ref.wav"
    out = tmp_path / "out/derived.wav"

    converter.timbre(source, target, out)

    assert runner.commands == [[
        str(converter.binary),
        "--task", "vc",
        "--family", "tone_color_vc",
        "--backend", "cuda",
        "--model", str(converter.model),
        "--audio", str(source),
        "--voice-ref", str(target),
        "--out", str(out),
    ]]
    assert runner.timeouts == [42]
    assert out.exists()


def test_a_non_zero_exit_is_a_render_failure_with_the_stderr_tail(
    tmp_path,
):
    runner = RecordingRunner(code=1, output="line one\nboom: bad gguf\n", write=False)
    converter = AudiocppTimbre(
        tmp_path / "bin", tmp_path / "model.gguf", runner=runner
    )

    with pytest.raises(RenderFailed, match="bad gguf"):
        converter.timbre(tmp_path / "a.wav", tmp_path / "b.wav", tmp_path / "o.wav")


def test_an_empty_file_is_a_render_failure(tmp_path):
    def runner(command, timeout):
        Path(command[command.index("--out") + 1]).write_bytes(b"")
        return 0, ""

    converter = AudiocppTimbre(tmp_path / "bin", tmp_path / "model.gguf", runner=runner)

    with pytest.raises(RenderFailed, match="produced no audio"):
        converter.timbre(tmp_path / "a.wav", tmp_path / "b.wav", tmp_path / "o.wav")
