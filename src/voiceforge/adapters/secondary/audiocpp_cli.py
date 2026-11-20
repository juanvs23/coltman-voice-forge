"""audio.cpp CLI adapter: Ming-3.0 in GGUF, no Python model stack.

Design notes
------------
* The CLI is the verified interface. The server has an OpenAI-compatible
  endpoint, but its task/options schema for `vdes`/`clon` is undocumented, and
  guessing a contract is how adapters rot. This adapter shells out to
  ``audiocpp_cli`` and keeps the model path in one place.
* Every model call is one process. That costs a model load per line (~2-3 s
  warm page cache). It is the honest cost of not having a documented server
  protocol yet; the lifecycle reports ``cli`` instead of pretending to be warm.
"""

from __future__ import annotations

import subprocess
import tempfile
import wave
from pathlib import Path
from typing import Mapping, Sequence

from ...domain.errors import EngineUnavailable, ValidationError
from ...domain.models import (
    DesignCandidate,
    Emotion,
    EmotionAxis,
    Voice,
    VoiceBrief,
)

DEFAULT_PREVIEW = (
    "La casa llevaba veinte años vacía. Ahora alguien ha encendido la luz del pasillo."
)

# The model speaks Spanish; the instruction is written in the language of the
# product. Ming was trained on Chinese/English instructions, so keep these
# short and concrete.
_AXIS_WORDS: dict[EmotionAxis, str] = {
    EmotionAxis.HAPPY: "alegre",
    EmotionAxis.ANGRY: "enfadado",
    EmotionAxis.SAD: "triste",
    EmotionAxis.AFRAID: "aterrado",
    EmotionAxis.DISGUSTED: "con asco",
    EmotionAxis.MELANCHOLIC: "melancólico",
    EmotionAxis.SURPRISED: "sorprendido",
    EmotionAxis.CALM: "sereno",
}


def _strength(value: float) -> str:
    if value < 0.35:
        return "levemente"
    if value < 0.7:
        return "claramente"
    return "intensamente"


def build_instruct(emotion: Emotion, speed: float = 1.0) -> str | None:
    """Compose a freeform instruction from the domain's axes.

    Pure function: this is the only place where the eight axes become words.
    """
    parts = [
        f"{_strength(value)} {_AXIS_WORDS[axis]}"
        for axis, value in sorted(emotion.axes.items(), key=lambda item: item[0].value)
    ]
    if speed and speed < 0.92:
        parts.append("ritmo lento y pausado")
    elif speed and speed > 1.08:
        parts.append("ritmo rápido")
    if emotion.hint:
        parts.append(emotion.hint)
    if not parts:
        return None
    return ", ".join(parts)


def _wav_duration(path: Path) -> float:
    with wave.open(str(path), "rb") as handle:
        return handle.getnframes() / float(handle.getframerate())


class AudiocppCli:
    """Implements VoiceDesigner + SpeechSynthesizer over the audio.cpp CLI."""

    def __init__(
        self,
        binary: Path,
        model: Path,
        *,
        backend: str = "cpu",
        threads: int | None = None,
        timeout_s: float = 900.0,
        runner=None,
    ) -> None:
        self.binary = Path(binary)
        self.model = Path(model)
        self.backend = backend
        self.threads = threads
        self._timeout = timeout_s
        self._run = runner or _run

    # ── VoiceDesigner ───────────────────────────────────────────────────
    def design(self, brief: VoiceBrief) -> Sequence[DesignCandidate]:
        preview = brief.preview_text or DEFAULT_PREVIEW
        base_seed = brief.seed if brief.seed is not None else 1895
        candidates: list[DesignCandidate] = []

        for index in range(brief.candidates):
            seed = base_seed + index
            with tempfile.TemporaryDirectory() as tmp:
                out = Path(tmp) / f"candidate-{index}.wav"
                command = self._base("vdes") + [
                    "--text", preview,
                    "--out", str(out),
                    "--request-option", f"language={_lang(brief.language)}",
                    "--request-option", f"instruct={brief.description}",
                    "--request-option", f"seed={seed}",
                ]
                self._must(command, "voice design failed")
                if not out.exists():
                    raise EngineUnavailable("the runtime produced no audio for the design request")
                candidates.append(
                    DesignCandidate(
                        index=index,
                        audio=out.read_bytes(),
                        sample_rate=_sample_rate(out),
                        recipe={
                            "task": "vdes",
                            "model": str(self.model),
                            "instruct": brief.description,
                            "preview_text": preview,
                            "language": brief.language,
                            "seed": seed,
                        },
                    )
                )
        return candidates

    # ── SpeechSynthesizer ───────────────────────────────────────────────
    def synthesize(
        self,
        *,
        text: str,
        voice: Voice,
        emotion: Emotion,
        speed: float,
        out_path: Path,
    ) -> float:
        out_path = Path(out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)

        instruct = build_instruct(emotion, speed)
        command = self._base("clon") + [
            "--voice-ref", str(voice.ref_audio),
            "--text", text,
            "--out", str(out_path),
            "--request-option", f"language={_lang(voice.language)}",
        ]
        if voice.ref_transcript:
            command += ["--request-option", f"reference_text={voice.ref_transcript}"]
        if instruct:
            # One path for delivery: emotion and pace are words, not slots.
            command += [
                "--request-option", "template_name=freeform",
                "--request-option", f"instruct={instruct}",
            ]
        seed = voice.recipe.get("seed")
        if isinstance(seed, int):
            command += ["--request-option", f"seed={seed}"]

        self._must(command, "synthesis failed")
        if not out_path.exists():
            raise EngineUnavailable("the runtime produced no audio for the synthesis request")
        return _wav_duration(out_path)

    # ── internals ───────────────────────────────────────────────────────
    def _base(self, task: str) -> list[str]:
        command = [
            str(self.binary),
            "--family", "ming3_tts",
            "--task", task,
            "--backend", self.backend,
            "--model", str(self.model),
        ]
        if self.threads:
            command += ["--threads", str(self.threads)]
        return command

    def _must(self, command: list[str], message: str) -> None:
        code, output = self._run(command, self._timeout)
        if code != 0:
            tail = " | ".join(output.strip().splitlines()[-6:])
            raise EngineUnavailable(f"{message}: {tail}")


def _lang(language: str) -> str:
    table = {
        "spanish": "es", "español": "es", "es": "es",
        "english": "en", "en": "en",
        "chinese": "zh", "zh": "zh",
        "japanese": "ja", "ja": "ja",
        "korean": "ko", "ko": "ko",
        "german": "de", "de": "de",
        "french": "fr", "fr": "fr",
    }
    key = language.strip().lower()
    if key not in table:
        raise ValidationError(f"language not supported by this runtime: {language!r}")
    return table[key]


def _sample_rate(path: Path) -> int:
    try:
        with wave.open(str(path), "rb") as handle:
            return int(handle.getframerate())
    except Exception:  # noqa: BLE001
        return 44_100


def _run(command: Sequence[str], timeout: float) -> tuple[int, str]:
    try:
        result = subprocess.run(  # noqa: S603 - fixed local binary
            list(command), capture_output=True, text=True, timeout=timeout, check=False
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 1, str(exc)
    return result.returncode, (result.stdout or "") + (result.stderr or "")


class AudiocppControl:
    """Lifecycle for the CLI backend: there is no long-lived host to warm.

    Saying that out loud is better than faking a warm state: `up` reports
    ``cli`` and `down` is a no-op.
    """

    def __init__(self, binary: Path, model: Path, backend: str) -> None:
        self._binary = Path(binary)
        self._model = Path(model)
        self._backend = backend

    def up(self) -> Mapping[str, object]:
        return {"status": "cli", "reason": "this backend loads the model per call"}

    def warm(self, modes: Sequence[str] | None = None) -> Mapping[str, object]:
        return {"warmed": False, "reason": "no long-lived host in cli mode"}

    def status(self) -> Mapping[str, object]:
        return {
            "status": "cli",
            "backend": self._backend,
            "model": str(self._model),
            "binary": str(self._binary),
            "binary_present": self._binary.exists(),
            "model_present": self._model.exists(),
        }

    def down(self) -> Mapping[str, object]:
        return {"status": "down"}
