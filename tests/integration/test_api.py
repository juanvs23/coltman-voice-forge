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
    response = client.get("/")
    assert response.status_code == 200
    assert "voice-forge" in response.text


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
