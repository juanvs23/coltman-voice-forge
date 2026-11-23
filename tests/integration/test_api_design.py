"""Design endpoints: audition candidates first, register the chosen one after.

Fakes only. The contract under test is the two-step split: the audition writes
files and answers with a token; the register step reads that token back, never
a path or a recipe sent by the client.
"""

from __future__ import annotations

import json
import re

import pytest
from fastapi.testclient import TestClient

from voiceforge.adapters.primary.http import create_app


@pytest.fixture
def client(container) -> TestClient:
    return TestClient(create_app(container))


def _audition(client, **overrides):
    body = {"description": "narrador grave", "candidates": 2, **overrides}
    return client.post("/api/voices/design/candidates", json=body)


def _auditions(container):
    return container.settings.out_dir / "candidates"


def _voice_json(container, slug: str) -> dict:
    path = container.settings.catalog_dir / slug / "voice.json"
    return json.loads(path.read_text(encoding="utf-8"))


# ── candidates ──────────────────────────────────────────────────────────
def test_candidates_answer_with_a_token_and_playable_urls(client, container):
    response = _audition(client, seed=5)

    assert response.status_code == 201
    data = response.json()
    assert re.fullmatch(r"[0-9a-f]{12}", data["token"])
    token = data["token"]
    assert [entry["index"] for entry in data["candidates"]] == [0, 1]
    assert [entry["url"] for entry in data["candidates"]] == [
        f"/candidates/{token}-0.wav",
        f"/candidates/{token}-1.wav",
    ]

    directory = _auditions(container)
    for entry in data["candidates"]:
        assert (directory / f"{token}-{entry['index']}.wav").is_file()
    sidecar = json.loads((directory / f"{token}.json").read_text(encoding="utf-8"))
    assert sidecar["brief"]["description"] == "narrador grave"
    assert sidecar["brief"]["seed"] == 5
    assert sidecar["brief"]["emotional"] is False
    assert len(sidecar["candidates"]) == 2


def test_candidate_audio_is_served(client):
    token = _audition(client).json()["token"]

    response = client.get(f"/candidates/{token}-0.wav")

    assert response.status_code == 200
    assert response.content == b"RIFF-fake-0"


def test_a_new_audition_replaces_the_previous_files(client, container):
    first = _audition(client).json()["token"]
    second = _audition(client, candidates=3).json()["token"]

    directory = _auditions(container)
    assert sorted(path.name for path in directory.iterdir()) == sorted(
        [
            f"{second}-0.wav",
            f"{second}-1.wav",
            f"{second}-2.wav",
            f"{second}.json",
        ]
    )
    assert client.get(f"/candidates/{first}-0.wav").status_code == 404


def test_candidates_do_not_register_anything(client):
    _audition(client)

    assert client.get("/api/voices").json() == []


def test_candidates_with_an_emotional_brief_are_refused_without_consent(
    client, container
):
    response = _audition(client, description="una voz triste")

    assert response.status_code == 400
    assert "triste" in response.json()["error"]
    assert list(_auditions(container).iterdir()) == []


# ── register ────────────────────────────────────────────────────────────
def test_register_creates_the_voice_from_the_token(client, container):
    data = _audition(client).json()

    response = client.post(
        "/api/voices/design/register",
        json={
            "token": data["token"],
            "pick": 1,
            "slug": "elegida",
            "name": "Elegida",
            "tags": ["demo"],
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["voice"] == {
        "slug": "elegida",
        "name": "Elegida",
        "origin": "designed",
    }
    assert body["picked"] == 1
    assert body["candidates"] == 2

    voice = container.catalog.get("elegida")
    assert voice.recipe["brief"] == "narrador grave"
    assert voice.recipe["picked"] == 1
    assert voice.recipe["candidates"] == 2
    assert voice.recipe["instruct"] == "narrador grave"
    assert voice.tags == ("demo",)
    assert voice.reference_neutral is True


def test_register_ignores_paths_and_recipes_sent_by_the_client(client, container):
    token = _audition(client).json()["token"]

    response = client.post(
        "/api/voices/design/register",
        json={
            "token": token,
            "slug": "elegida",
            "file": "/etc/passwd",
            "recipe": {"evil": True},
        },
    )

    assert response.status_code == 201
    voice = container.catalog.get("elegida")
    assert "evil" not in voice.recipe
    assert voice.recipe["instruct"] == "narrador grave"
    assert voice.ref_audio.read_bytes() == b"RIFF-fake-0"


def test_register_writes_the_same_voice_json_as_the_one_call_endpoint(
    client, container
):
    brief = {"description": "narrador grave", "language": "Spanish", "candidates": 2}

    one_call = client.post(
        "/api/voices/design", json={**brief, "slug": "one-call", "tags": ["demo"]}
    )
    assert one_call.status_code == 201

    token = _audition(client, **brief).json()["token"]
    two_step = client.post(
        "/api/voices/design/register",
        json={"token": token, "slug": "two-step", "tags": ["demo"]},
    )
    assert two_step.status_code == 201

    left = _voice_json(container, "one-call")
    right = _voice_json(container, "two-step")
    assert left["recipe"] == right["recipe"]
    for payload in (left, right):
        payload.pop("slug")
        payload.pop("name")
    assert left == right


def test_a_candidate_registered_by_the_console_matches_the_endpoint(
    client, container
):
    """The console skips HTTP but not the contract: same recipe, same voice.json."""
    from voiceforge.adapters.primary.webui.context import UiContext
    from voiceforge.adapters.primary.webui.design import (
        design_candidates,
        register_choice,
    )

    endpoint = client.post(
        "/api/voices/design",
        json={
            "description": "narrador grave",
            "slug": "via-api",
            "candidates": 2,
            "tags": ["demo"],
        },
    )
    assert endpoint.status_code == 201

    ctx = UiContext.from_container(container)
    _, state, _ = design_candidates(
        ctx, "narrador grave", "Spanish", 2, None, None, False
    )
    message, _ = register_choice(ctx, state, 0, "via-console", None, "demo", False)
    assert "Registered" in message

    left = _voice_json(container, "via-api")
    right = _voice_json(container, "via-console")
    assert left["recipe"] == right["recipe"]
    assert left["ref_sha256"] == right["ref_sha256"]
    for payload in (left, right):
        payload.pop("slug")
        payload.pop("name")
    assert left == right


def test_register_with_a_well_formed_unknown_token_is_404(client):
    response = client.post(
        "/api/voices/design/register",
        json={"token": "0123456789ab", "slug": "ghost"},
    )

    assert response.status_code == 404


@pytest.mark.parametrize("token", ["", "../../etc/passwd", "ABCDEF012345", "short"])
def test_register_with_a_malformed_token_is_400(client, token):
    response = client.post(
        "/api/voices/design/register", json={"token": token, "slug": "ghost"}
    )

    assert response.status_code == 400


def test_register_with_a_pick_outside_the_audition_is_400(client):
    token = _audition(client).json()["token"]

    response = client.post(
        "/api/voices/design/register",
        json={"token": token, "pick": 5, "slug": "ghost"},
    )

    assert response.status_code == 400
    assert "pick" in response.json()["error"]


def test_register_with_a_taken_slug_is_400(client):
    token = _audition(client).json()["token"]
    client.post(
        "/api/voices/design/register",
        json={"token": token, "slug": "elegida"},
    )

    response = client.post(
        "/api/voices/design/register",
        json={"token": token, "slug": "elegida"},
    )

    assert response.status_code == 400
    assert "already in the catalog" in response.json()["error"]


def test_register_honours_the_emotional_flag(client, container):
    token = _audition(client, description="una voz triste", emotional=True).json()[
        "token"
    ]

    refused = client.post(
        "/api/voices/design/register", json={"token": token, "slug": "triste-voz"}
    )
    assert refused.status_code == 400
    assert "triste" in refused.json()["error"]

    accepted = client.post(
        "/api/voices/design/register",
        json={"token": token, "slug": "triste-voz", "emotional": True},
    )
    assert accepted.status_code == 201
    assert container.catalog.get("triste-voz").reference_neutral is False
