"""audio.cpp server adapter: the model stays resident.

Why this exists next to the CLI adapter: the CLI pays a model load per call.
The server loads once and answers `/v1/audio/speech`, so narration stops paying
for startup. Measured on CPU: ~6.9 s per short line either way *after* warm-up,
versus ~12 s through the CLI — the difference is the load, not the model.

Contract used here was discovered empirically against `audiocpp_server` and is
covered by tests; it is not guessed:

    POST /v1/audio/speech
    {"model": "<entry id>", "input": "<text>", "voice": "<reference path>",
     "options": {"language": "es", "template_name": "freeform",
                 "instruct": "...", "reference_text": "...", "seed": 1895}}
    -> 200 with a WAV body
"""

from __future__ import annotations

import io
import json
import subprocess
import time
import wave
from pathlib import Path
from typing import Mapping, Sequence

import httpx

from ...domain.errors import EngineAlreadyRunning, EngineUnavailable
from ...domain.models import DesignCandidate, Emotion, Voice, VoiceBrief
from .audiocpp_cli import DEFAULT_PREVIEW, _lang, build_instruct

DESIGN_MODEL_ID = "ming-vdes"
SPEECH_MODEL_ID = "ming-tts"


def server_config(model: Path, design_id: str = DESIGN_MODEL_ID, speech_id: str = SPEECH_MODEL_ID) -> dict:
    """Two entries over the same GGUF: one designs, one performs."""
    entry = {"family": "ming3_tts", "mode": "offline", "path": str(model)}
    return {
        "models": [
            {"id": speech_id, "task": "tts", **entry},
            {"id": design_id, "task": "vdes", **entry},
        ]
    }


class AudiocppServer:
    """VoiceDesigner + SpeechSynthesizer over the resident server."""

    def __init__(self, base_url: str = "http://127.0.0.1:8731", timeout_s: float = 900.0, client=None):
        self.base_url = base_url.rstrip("/")
        self._timeout = timeout_s
        self._client = client

    # ── ports ───────────────────────────────────────────────────────────
    def design(self, brief: VoiceBrief) -> Sequence[DesignCandidate]:
        preview = brief.preview_text or DEFAULT_PREVIEW
        base_seed = brief.seed if brief.seed is not None else 1895
        candidates: list[DesignCandidate] = []

        for index in range(brief.candidates):
            seed = base_seed + index
            audio = self._speech(
                model=DESIGN_MODEL_ID,
                text=preview,
                options={
                    "language": _lang(brief.language),
                    "instruct": brief.description,
                    "seed": seed,
                },
            )
            candidates.append(
                DesignCandidate(
                    index=index,
                    audio=audio,
                    sample_rate=_wav_rate(audio),
                    recipe={
                        "task": "vdes",
                        "transport": "server",
                        "instruct": brief.description,
                        "preview_text": preview,
                        "language": brief.language,
                        "seed": seed,
                    },
                )
            )
        return candidates

    def synthesize(
        self,
        *,
        text: str,
        voice: Voice,
        emotion: Emotion,
        speed: float,
        out_path: Path,
    ) -> float:
        instruct = build_instruct(emotion, speed)
        options: dict[str, object] = {"language": _lang(voice.language)}
        # Deliberately no `reference_text`: it enables the acoustic-prefix (ICL)
        # mode, which measured 22 s and produced 5.1 s of audio for a 2.6 s line
        # (the model continues the reference). Speaker-only conditioning is 9.5 s
        # and the right length; identity lives in the speaker, performance in
        # the instruction.
        if instruct:
            options["template_name"] = "freeform"
            options["instruct"] = instruct
        seed = voice.recipe.get("seed")
        if isinstance(seed, int):
            options["seed"] = seed

        audio = self._speech(
            model=SPEECH_MODEL_ID,
            text=text,
            voice=str(voice.ref_audio),
            options=options,
        )
        out_path = Path(out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(audio)
        return _wav_duration(audio)

    # ── internals ───────────────────────────────────────────────────────
    def _speech(self, *, model: str, text: str, options: Mapping[str, object], voice: str | None = None) -> bytes:
        payload: dict[str, object] = {"model": model, "input": text, "options": dict(options)}
        if voice:
            # The server field is `voice_ref` (path string, or {type,path|data}).
            payload["voice_ref"] = voice
        try:
            client = self._client or httpx.Client(timeout=self._timeout)
            try:
                response = client.post(f"{self.base_url}/v1/audio/speech", json=payload)
            finally:
                if self._client is None:
                    client.close()
        except httpx.HTTPError as exc:
            raise EngineUnavailable(f"audio.cpp server did not answer: {exc}") from exc

        if response.status_code != 200:
            raise EngineUnavailable(
                f"audio.cpp server rejected the request ({response.status_code}): "
                f"{response.text[:300]}"
            )
        if not response.content:
            raise EngineUnavailable("audio.cpp server returned an empty body")
        return response.content


class AudiocppServerControl:
    """Real on / warm / off for the resident server."""

    def __init__(
        self,
        binary: Path,
        model: Path,
        *,
        backend: str = "cpu",
        port: int = 8731,
        config_path: Path,
        log_path: Path,
        boot_timeout_s: float = 180.0,
    ) -> None:
        self._binary = Path(binary)
        self._model = Path(model)
        self._backend = backend
        self._port = port
        self._config_path = Path(config_path)
        self._log_path = Path(log_path)
        self._boot_timeout = boot_timeout_s
        self._base_url = f"http://127.0.0.1:{port}"

    def up(self) -> Mapping[str, object]:
        if self._healthy():
            raise EngineAlreadyRunning("the audio.cpp server is already running")
        if not self._binary.exists():
            raise EngineUnavailable(f"runtime binary not found: {self._binary}")

        self._config_path.parent.mkdir(parents=True, exist_ok=True)
        import json

        self._config_path.write_text(
            json.dumps(server_config(self._model), indent=2) + "\n", encoding="utf-8"
        )
        self._log_path.parent.mkdir(parents=True, exist_ok=True)
        log = open(self._log_path, "ab")
        process = subprocess.Popen(  # noqa: S603 - fixed local binary
            [
                str(self._binary),
                "--config", str(self._config_path),
                "--backend", self._backend,
                "--port", str(self._port),
                "--no-ui",
                "--max-loaded-models", "1",
            ],
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        deadline = time.monotonic() + self._boot_timeout
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise EngineUnavailable(
                    f"audio.cpp server exited with {process.returncode}; see {self._log_path}"
                )
            if self._healthy():
                return {"status": "up", "pid": process.pid, "url": self._base_url}
            time.sleep(1.0)
        raise EngineUnavailable(f"server did not answer within {self._boot_timeout:.0f}s")

    def warm(self, modes: Sequence[str] | None = None) -> Mapping[str, object]:
        """Load the speech entry by doing the smallest possible synthesis."""
        if not self._healthy():
            raise EngineUnavailable("server is down; run `voice-forge up` first")
        started = time.monotonic()
        client = httpx.Client(timeout=600)
        try:
            response = client.post(
                f"{self._base_url}/v1/audio/speech",
                json={"model": SPEECH_MODEL_ID, "input": "Hola.", "options": {"language": "es"}},
            )
        finally:
            client.close()
        if response.status_code != 200:
            raise EngineUnavailable(f"warm-up failed: {response.status_code} {response.text[:200]}")
        return {
            "warmed": True,
            "seconds": round(time.monotonic() - started, 1),
            "url": self._base_url,
        }

    def status(self) -> Mapping[str, object]:
        if not self._healthy():
            return {"status": "down", "url": self._base_url}
        return {"status": "up", "url": self._base_url, "backend": self._backend}

    def down(self, *, force: bool = False) -> Mapping[str, object]:
        try:
            client = httpx.Client(timeout=5)
            try:
                client.post(f"{self._base_url}/shutdown")
            finally:
                client.close()
        except httpx.HTTPError:
            pass
        time.sleep(1.0)
        subprocess.run(["pkill", "-x", "audiocpp_server"], check=False)  # noqa: S603,S607
        return {"status": "down"}

    def _healthy(self) -> bool:
        try:
            client = httpx.Client(timeout=2)
            try:
                return client.get(f"{self._base_url}/health").status_code == 200
            finally:
                client.close()
        except httpx.HTTPError:
            return False


def _wav_rate(audio: bytes) -> int:
    try:
        with wave.open(io.BytesIO(audio), "rb") as handle:
            return int(handle.getframerate())
    except Exception:  # noqa: BLE001
        return 44_100


def _wav_duration(audio: bytes) -> float:
    with wave.open(io.BytesIO(audio), "rb") as handle:
        return handle.getnframes() / float(handle.getframerate())
