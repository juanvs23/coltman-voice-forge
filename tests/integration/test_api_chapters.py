"""API contract for chaptered render: `chapter` toggles the response shape."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from voiceforge.adapters.primary.http import create_app

SCRIPT = """\
title: saga
## chapter: la casa
lines:
  - {voice: narrador, text: "La casa estaba vacía."}
## chapter: el pasillo
lines:
  - {voice: narrador, text: "Alguien encendió la luz."}
"""


@pytest.fixture
def client(container) -> TestClient:
    return TestClient(create_app(container))


@pytest.fixture
def voice(client):
    client.post(
        "/api/voices/design",
        json={"description": "narrador grave", "slug": "narrador", "candidates": 1},
    )


def test_render_with_chapter_returns_the_list(client, voice, tmp_path):
    response = client.post(
        "/api/dialogues/render",
        json={
            "script": SCRIPT,
            "out": str(tmp_path / "narracion.wav"),
            "chapter": True,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert [chapter["name"] for chapter in body["chapters"]] == ["la casa", "el pasillo"]
    assert [chapter["lines"] for chapter in body["chapters"]] == [1, 1]
    assert [chapter["lufs"] for chapter in body["chapters"]] == [-14.0, -14.0]
    assert [chapter["path"].rsplit("/", 1)[-1] for chapter in body["chapters"]] == [
        "narracion-01.wav",
        "narracion-02.wav",
    ]
    assert body["job"]


def test_render_without_chapter_keeps_the_old_shape(client, voice, tmp_path):
    response = client.post(
        "/api/dialogues/render",
        json={
            "script": "title: demo\nlines:\n  - {voice: narrador, text: 'Hola.'}\n",
            "out": str(tmp_path / "uno.wav"),
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert "chapters" not in body
    assert body["path"].endswith("uno.wav")
    assert body["lines"] == 1
