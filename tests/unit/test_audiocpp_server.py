"""Server adapter: request shape against the contract we verified by hand."""

from __future__ import annotations

import io
import json
import wave
from pathlib import Path

import httpx
import pytest

from voiceforge.adapters.secondary.audiocpp_server import (
    DESIGN_MODEL_ID,
    SPEECH_MODEL_ID,
    AudiocppServer,
    server_config,
)
from voiceforge.domain.errors import EngineUnavailable
from voiceforge.domain.models import Emotion, EmotionAxis, Voice, VoiceBrief


def wav_bytes(seconds: float = 0.5, rate: int = 44_100) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(b"\x00\x00" * int(rate * seconds))
    return buffer.getvalue()


class Recorder:
    def __init__(self, status: int = 200, body: bytes | None = None):
        self.requests: list[dict] = []
        self.status = status
        self.body = body if body is not None else wav_bytes()

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append({"path": request.url.path, "json": json.loads(request.content)})
        return httpx.Response(self.status, content=self.body)


def build(recorder: Recorder) -> AudiocppServer:
    client = httpx.Client(transport=httpx.MockTransport(recorder.handler))
    return AudiocppServer(client=client)


def test_server_config_declares_both_tasks_over_one_model(tmp_path):
    config = server_config(tmp_path / "ming.gguf")
    tasks = [entry["task"] for entry in config["models"]]
    assert tasks == ["tts", "vdes"]
    assert {entry["path"] for entry in config["models"]} == {str(tmp_path / "ming.gguf")}


def test_design_posts_vdes_with_language_and_seed():
    recorder = Recorder()
    candidates = build(recorder).design(VoiceBrief(description="narrador grave", candidates=2, seed=50))

    assert len(candidates) == 2
    assert len(recorder.requests) == 2
    first = recorder.requests[0]["json"]
    assert first["model"] == DESIGN_MODEL_ID
    assert first["options"]["language"] == "es"
    assert first["options"]["instruct"] == "narrador grave"
    assert [c.recipe["seed"] for c in candidates] == [50, 51]
    assert candidates[0].sample_rate == 44_100
    assert candidates[0].audio[:4] == b"RIFF"


def test_synthesize_posts_clone_with_voice_and_freeform(tmp_path):
    recorder = Recorder()
    ref = tmp_path / "ref.wav"
    ref.write_bytes(wav_bytes(1.0))
    voice = Voice(
        slug="narrador",
        name="Narrador",
        ref_audio=ref,
        language="Spanish",
        sample_rate=44_100,
        recipe={"seed": 1895},
        created_at="2026-11-20T00:00:00+00:00",
        ref_transcript="La casa estaba vacía.",
        ref_sha256="x" * 64,
    )
    out = tmp_path / "line.wav"

    duration = build(recorder).synthesize(
        text="Entra.",
        voice=voice,
        emotion=Emotion(axes={EmotionAxis.AFRAID: 0.9}),
        speed=0.9,
        out_path=out,
    )

    assert out.exists()
    assert duration == pytest.approx(0.5, abs=0.01)
    payload = recorder.requests[0]["json"]
    assert payload["model"] == SPEECH_MODEL_ID
    assert payload["input"] == "Entra."
    assert payload["voice_ref"] == str(ref)
    assert "reference_text" not in payload["options"]
    assert payload["options"]["template_name"] == "freeform"
    assert "aterrado" in payload["options"]["instruct"]
    assert payload["options"]["seed"] == 1895


def test_a_rejected_request_is_reported_with_the_server_message():
    recorder = Recorder(status=400, body=b'{"error":"bad option"}')
    with pytest.raises(EngineUnavailable) as exc:
        build(recorder).design(VoiceBrief(description="x", candidates=1))
    assert "bad option" in str(exc.value)


def test_an_empty_body_is_an_error_not_silence():
    recorder = Recorder(body=b"")
    with pytest.raises(EngineUnavailable):
        build(recorder).design(VoiceBrief(description="x", candidates=1))
