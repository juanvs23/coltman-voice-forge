"""Console contract: Gradio is mounted, the API stays the source of truth.

Mounting ``gr.Blocks`` builds an event loop in-process, so a run can print
``ResourceWarning: unclosed event loop`` at teardown. That is Gradio's
lifetime, not ours, and it is documented here instead of hidden behind a
``filterwarnings`` marker.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from voiceforge.adapters.primary.http import create_app
from voiceforge.adapters.primary.webui.app import build_console


@pytest.fixture
def client(container) -> TestClient:
    return TestClient(create_app(container))


def test_console_is_mounted(client):
    response = client.get("/ui")
    assert response.status_code == 200
    assert "voice-forge" in response.text
    # `/ui` hands off to `/ui/` so Gradio's relative asset URLs stay correct.
    assert "/ui/" in response.text
    assert client.get("/ui/").status_code == 200


def test_root_redirects_to_the_console(client):
    response = client.get("/", follow_redirects=False)
    assert response.status_code == 308
    assert response.headers["location"] == "/ui/"
    # The legacy page is gone: `/` is a redirect, never a rendered template.
    assert 'id="engine"' not in response.text


def test_header_counts_the_catalog_and_leaves_the_engine_wiring_to_its_tab(container):
    blocks = build_console(container)
    markdown = [
        block.value
        for block in blocks.blocks.values()
        if type(block).__name__ == "Markdown"
    ]

    header = markdown[0]
    assert header == "# voice-forge\n\n**0 voices**"
    # Adapter, device and model are the Engine tab's business, not the title.
    assert "adapter" not in header
    assert "device" not in header


def test_a_fresh_console_hides_the_advanced_and_action_controls(container):
    blocks = build_console(container)
    accordions = {
        block.label: block
        for block in blocks.blocks.values()
        if type(block).__name__ == "Accordion"
    }
    groups = [block for block in blocks.blocks.values() if type(block).__name__ == "Group"]

    assert set(accordions) == {
        "Derive a new voice",
        "Remove a voice",
        "Advanced: per-axis control",
    }
    assert not any(accordion.open for accordion in accordions.values())
    # Design: nothing to register until a candidate exists.
    assert [group.visible for group in groups] == [False]


def test_previews_always_report_three_slots(client):
    data = client.get("/api/previews").json()
    assert [entry["slot"] for entry in data] == [0, 1, 2]
    assert all(entry == {"slot": entry["slot"], "empty": True} for entry in data)


def test_previews_read_the_sidecars_and_keep_gaps_empty(client, container):
    previews = container.settings.out_dir / "previews"
    previews.mkdir(parents=True, exist_ok=True)
    (previews / "slot-0.json").write_text(
        json.dumps(
            {
                "slot": 0,
                "voice": "narrador",
                "text": "La casa estaba vacía.",
                "axes": {"melancholic": 0.4},
                "intensity": 0.6,
                "speed": 1.0,
                "duration_s": 1.5,
            }
        ),
        encoding="utf-8",
    )
    (previews / "slot-2.json").write_text(
        json.dumps({"slot": 2, "voice": "clon", "text": "Hola.", "duration_s": 0.8}),
        encoding="utf-8",
    )

    data = client.get("/api/previews").json()

    assert data[0] == {
        "slot": 0,
        "empty": False,
        "voice": "narrador",
        "text": "La casa estaba vacía.",
        "axes": {"melancholic": 0.4},
        "intensity": 0.6,
        "speed": 1.0,
        "duration_s": 1.5,
        "url": "/previews/slot-0.wav",
    }
    assert data[1] == {"slot": 1, "empty": True}
    assert data[2]["empty"] is False
    assert data[2]["voice"] == "clon"
    assert data[2]["url"] == "/previews/slot-2.wav"


def test_corrupt_sidecar_degrades_to_empty(client, container):
    previews = container.settings.out_dir / "previews"
    previews.mkdir(parents=True, exist_ok=True)
    (previews / "slot-1.json").write_text("{not json", encoding="utf-8")

    data = client.get("/api/previews").json()

    assert data[1] == {"slot": 1, "empty": True}
