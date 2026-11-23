"""API contract tests: fakes only, no engine, no GPU."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from voiceforge.adapters.primary.http import create_app


@pytest.fixture
def client(container) -> TestClient:
    return TestClient(create_app(container))


def test_health_of_the_engine_proxy(client):
    response = client.get("/api/engine")
    assert response.status_code == 200
    assert response.json()["status"] == "up"


def test_ui_is_served(client):
    response = client.get("/", follow_redirects=False)
    assert response.status_code == 308
    assert response.headers["location"] == "/ui/"
    assert client.get("/ui").status_code == 200
    assert client.get("/ui/").status_code == 200


def test_design_then_list(client):
    response = client.post(
        "/api/voices/design",
        json={"description": "narrador grave", "slug": "narrador", "candidates": 2},
    )
    assert response.status_code == 201
    assert response.json()["voice"]["slug"] == "narrador"

    listing = client.get("/api/voices").json()
    assert [voice["slug"] for voice in listing] == ["narrador"]

    # the generated voice is used like any imported one
    render = client.post(
        "/api/dialogues/render",
        json={
            "script": (
                "title: demo\n"
                "lines:\n"
                "  - voice: narrador\n"
                "    text: 'La casa estaba vacía.'\n"
                "    emotion: { melancholic: 0.4 }\n"
            ),
            "out": "/tmp/voice-forge-api-test.wav",
        },
    )
    assert render.status_code == 200
    assert render.json()["lines"] == 1


def test_design_with_taken_slug_returns_400(client):
    client.post("/api/voices/design", json={"description": "a", "slug": "voz"})
    response = client.post("/api/voices/design", json={"description": "b", "slug": "voz"})
    assert response.status_code == 400


def test_unknown_voice_returns_404(client):
    assert client.get("/api/voices/nope").status_code == 404
    assert client.delete("/api/voices/nope").status_code == 404


def test_upload_requires_a_file(client):
    response = client.post("/api/voices", data={"slug": "clon"})
    assert response.status_code == 422


def test_upload_registers_an_imported_voice(client):
    response = client.post(
        "/api/voices",
        data={"slug": "clon", "name": "Clon", "language": "Spanish"},
        files={"file": ("ref.wav", b"RIFF-fake", "audio/wav")},
    )
    assert response.status_code == 201
    assert response.json()["origin"] == "imported"


def test_engine_unknown_action(client):
    assert client.post("/api/engine/explode").status_code == 400


def test_queue_endpoint_reports_state(client):
    data = client.get("/api/queue").json()
    assert data["busy"] is False
    assert data["pending"] == 0


def test_starting_a_second_instance_is_rejected(container):
    from voiceforge.domain.errors import EngineAlreadyRunning

    class Running:
        def up(self):
            raise EngineAlreadyRunning("one instance only")

        def warm(self, modes=None):
            return {}

        def status(self):
            return {"status": "up"}

        def down(self, force=False):
            return {"status": "down"}

    container.engine = Running()
    from fastapi.testclient import TestClient

    from voiceforge.adapters.primary.http import create_app

    client = TestClient(create_app(container))
    response = client.post("/api/engine/up")
    assert response.status_code == 409
    assert "one instance" in response.json()["error"]


def test_derive_endpoint_creates_a_new_voice(client):
    client.post("/api/voices/design", json={"description": "narrador grave", "slug": "base"})
    response = client.post("/api/voices/base/derive", json={"slug": "base-grave", "pitch": -3})
    assert response.status_code == 201
    body = response.json()
    assert body["origin"] == "derived"
    assert body["derived_from"] == "base"
    assert body["pitch_semitones"] == -3
    assert body["job"]
    assert [voice["slug"] for voice in client.get("/api/voices").json()] == ["base", "base-grave"]


def test_derive_endpoint_accepts_a_timbre_and_quotes_no_pitch(client):
    client.post("/api/voices/design", json={"description": "narrador grave", "slug": "base"})
    client.post("/api/voices/design", json={"description": "otro narrador", "slug": "target"})

    response = client.post(
        "/api/voices/base/derive",
        json={"slug": "base-hibrido", "timbre": "target"},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["origin"] == "derived"
    assert body["derived_from"] == "base"
    assert body["timbre_from"] == "target"
    assert body["pitch_semitones"] is None

    recipe = client.get("/api/voices/base-hibrido").json()["recipe"]
    assert recipe["transform"] == "timbre"
    assert recipe["timbre_from"] == "target"
    assert recipe["model"] == "tone-color-vc-f16"
    # The conversion is model work: it passed through the serial queue.
    assert client.get("/api/queue").json()["history"][-1]["kind"] == "derive"


def test_derive_endpoint_rejects_pitch_and_timbre_together(client):
    client.post("/api/voices/design", json={"description": "narrador grave", "slug": "base"})
    client.post("/api/voices/design", json={"description": "otro narrador", "slug": "target"})

    response = client.post(
        "/api/voices/base/derive",
        json={"slug": "base-hibrido", "pitch": -2.0, "timbre": "target"},
    )

    assert response.status_code == 400
    assert "not both" in response.json()["error"]
