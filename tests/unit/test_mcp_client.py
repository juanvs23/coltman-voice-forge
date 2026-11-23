"""MCP client: request shape against the API contract, and error mapping."""

from __future__ import annotations

import json

import httpx
import pytest

from voiceforge.adapters.primary.mcp.client import (
    ApiError,
    ApiUnavailable,
    VoiceForgeClient,
)


class Recorder:
    def __init__(self, status: int = 200, payload=None, text: str | None = None):
        self.requests: list[httpx.Request] = []
        self.status = status
        self.payload = payload
        self.text = text

    def handler(self, request: httpx.Request) -> httpx.Response:
        request.read()
        self.requests.append(request)
        if self.text is not None:
            return httpx.Response(self.status, text=self.text)
        return httpx.Response(self.status, json=self.payload)


def client_for(recorder: Recorder) -> VoiceForgeClient:
    return VoiceForgeClient(
        "http://127.0.0.1:8720",
        transport=httpx.MockTransport(recorder.handler),
    )


def body(request: httpx.Request) -> dict:
    return json.loads(request.content)


def timeout_of(request: httpx.Request, key: str = "read") -> float | None:
    return request.extensions["timeout"].get(key)


def test_list_voices_gets_the_catalog():
    recorder = Recorder(payload=[{"slug": "alex"}])
    result = client_for(recorder).list_voices()

    assert result == [{"slug": "alex"}]
    assert recorder.requests[0].method == "GET"
    assert recorder.requests[0].url.path == "/api/voices"


def test_show_voice_escapes_nothing_and_hits_the_slug_route():
    recorder = Recorder(payload={"slug": "alex-grave"})
    assert client_for(recorder).show_voice("alex-grave") == {"slug": "alex-grave"}
    assert recorder.requests[0].url.path == "/api/voices/alex-grave"


def test_preview_voice_sends_the_emotion_payload_and_waits_nine_hundred_seconds():
    recorder = Recorder(payload={"path": "x.wav", "slot": 0})
    client = client_for(recorder)

    client.preview_voice(
        "narrador-terror",
        "La puerta se cerró.",
        axes={"afraid": 0.8, "calm": 0.1},
        intensity=0.7,
        speed=0.9,
        hint="susurrante",
    )

    request = recorder.requests[0]
    assert request.method == "POST"
    assert request.url.path == "/api/voices/narrador-terror/preview"
    assert body(request) == {
        "text": "La puerta se cerró.",
        "axes": {"afraid": 0.8, "calm": 0.1},
        "intensity": 0.7,
        "speed": 0.9,
        "hint": "susurrante",
    }
    assert timeout_of(request) == 900.0


def test_render_dialogue_sends_raw_yaml_and_allows_an_hour():
    recorder = Recorder(payload={"path": "out/render.wav", "lines": 2})
    script = "lines:\n  - voice: alex\n    text: hola\n"

    client_for(recorder).render_dialogue(script, out="out/x.wav", master=False)

    request = recorder.requests[0]
    assert request.url.path == "/api/dialogues/render"
    assert body(request) == {"script": script, "out": "out/x.wav", "master": False}
    assert timeout_of(request) == 3600.0


def test_design_candidates_sends_the_brief_and_waits_thirty_minutes():
    recorder = Recorder(payload={"token": "t", "candidates": []})

    client_for(recorder).design_candidates(
        "voz grave",
        candidates=2,
        language="Spanish",
        seed=7,
        preview_text="hola",
        emotional=True,
    )

    request = recorder.requests[0]
    assert request.url.path == "/api/voices/design/candidates"
    assert body(request) == {
        "description": "voz grave",
        "candidates": 2,
        "language": "Spanish",
        "seed": 7,
        "preview_text": "hola",
        "emotional": True,
    }
    assert timeout_of(request) == 1800.0


def test_register_candidate_posts_the_token_and_pick():
    recorder = Recorder(payload={"voice": {"slug": "nueva"}})

    client_for(recorder).register_candidate(
        "tok", 1, "nueva", name="Nueva", tags=["grave"], emotional=False
    )

    request = recorder.requests[0]
    assert request.url.path == "/api/voices/design/register"
    assert body(request) == {
        "token": "tok",
        "pick": 1,
        "slug": "nueva",
        "name": "Nueva",
        "tags": ["grave"],
        "emotional": False,
    }
    assert timeout_of(request) == 120.0


def test_clone_voice_uploads_the_file_as_multipart(tmp_path):
    clip = tmp_path / "mi-clon.wav"
    clip.write_bytes(b"RIFFfake-wave")

    recorder = Recorder(payload={"slug": "mi-clon"})
    client_for(recorder).clone_voice(
        str(clip), "mi-clon", name="Mi clon", transcript="hola", emotional=True
    )

    request = recorder.requests[0]
    assert request.method == "POST"
    assert request.url.path == "/api/voices"
    assert request.headers["content-type"].startswith("multipart/form-data")
    assert b'name="slug"' in request.content
    assert b"mi-clon" in request.content
    assert b'name="transcript"' in request.content
    assert b"\r\nhola\r\n" in request.content
    assert b'name="emotional"' in request.content
    assert b"\r\ntrue\r\n" in request.content
    assert b'filename="mi-clon.wav"' in request.content
    assert b"RIFFfake-wave" in request.content
    assert timeout_of(request) == 120.0


def test_derive_voice_puts_the_new_slug_in_the_body():
    recorder = Recorder(payload={"slug": "alex-grave-new"})

    client_for(recorder).derive_voice("alex", "alex-grave-new", name="N", pitch=-3.0)

    request = recorder.requests[0]
    assert request.url.path == "/api/voices/alex/derive"
    assert body(request) == {
        "slug": "alex-grave-new",
        "name": "N",
        "pitch": -3.0,
        "tags": [],
    }
    assert timeout_of(request) == 300.0


@pytest.mark.parametrize(
    ("call", "path"),
    [
        (lambda c: c.previews(), "/api/previews"),
        (lambda c: c.engine_status(), "/api/engine"),
        (lambda c: c.engine_action("warm"), "/api/engine/warm"),
        (lambda c: c.queue_status(), "/api/queue"),
    ],
)
def test_diagnostic_routes_are_fast(call, path):
    recorder = Recorder(payload={})
    call(client_for(recorder))

    request = recorder.requests[0]
    assert request.url.path == path
    assert timeout_of(request) == 15.0


def test_a_refused_connection_names_the_command_that_starts_the_api():
    def refused(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    client = VoiceForgeClient("http://127.0.0.1:9999", transport=httpx.MockTransport(refused))

    with pytest.raises(ApiUnavailable) as captured:
        client.list_voices()

    message = str(captured.value)
    assert "voice-forge serve is not running on http://127.0.0.1:9999" in message
    assert "`voice-forge serve`" in message


def test_a_connect_timeout_is_also_unavailable():
    def timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("too slow", request=request)

    client = VoiceForgeClient("http://api.test", transport=httpx.MockTransport(timeout))

    with pytest.raises(ApiUnavailable):
        client.engine_status()


def test_an_error_status_keeps_the_api_error_and_hint():
    recorder = Recorder(
        status=409,
        payload={"error": "engine is busy", "hint": "wait, or force with --force"},
    )

    with pytest.raises(ApiError) as captured:
        client_for(recorder).engine_action("down")

    error = captured.value
    assert error.status == 409
    assert error.error == "engine is busy"
    assert error.hint == "wait, or force with --force"
    assert "engine is busy" in str(error)
    assert "wait, or force with --force" in str(error)


def test_a_plain_text_error_body_is_reported_raw():
    recorder = Recorder(status=500, text="boom")

    with pytest.raises(ApiError) as captured:
        client_for(recorder).queue_status()

    assert captured.value.status == 500
    assert captured.value.error == "boom"
    assert captured.value.hint is None


def test_base_url_can_come_from_the_environment(monkeypatch):
    monkeypatch.setenv("VOICEFORGE_API_URL", "http://127.0.0.1:1234/")
    assert VoiceForgeClient().base_url == "http://127.0.0.1:1234"
