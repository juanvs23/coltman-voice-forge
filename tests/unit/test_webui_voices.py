"""Voices screen, no browser: cards and the three catalog actions.

Every assertion goes through the pure functions ``voices.py`` exposes; nothing
here builds ``gr.Blocks`` (``tests/integration/test_console.py`` owns the mount).
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from voiceforge.adapters.primary.webui.context import UiContext
from voiceforge.adapters.primary.webui.styles import CONSOLE_CSS
from voiceforge.adapters.primary.webui.voices import (
    cards_html,
    derive_voice,
    preview_ready,
    remove_voice,
    voices_table,
)
from voiceforge.domain.errors import VoiceNotFound
from voiceforge.domain.models import VoiceBrief


@pytest.fixture
def ctx(container) -> UiContext:
    return UiContext.from_container(container)


def _seed_three_origins(container) -> None:
    container.catalog.register(b"RIFF-imported", slug="imported-one", name="Imported One")
    container.catalog.design(
        VoiceBrief(description="un narrador neutro"),
        slug="designed-one",
        name="Designed One",
    )
    container.derive.derive("designed-one", slug="derived-one", pitch_semitones=-2.0)


# ── cards ───────────────────────────────────────────────────────────────
def test_cards_render_every_origin_distinctly(container):
    _seed_three_origins(container)

    markup = cards_html(container.catalog.list())

    assert "Imported One" in markup
    assert "Designed One" in markup
    for slug in ("imported-one", "designed-one", "derived-one"):
        assert slug in markup
    for origin in ("imported", "designed", "derived"):
        assert f'class="vf-badge vf-badge-{origin}">{origin}</span>' in markup
        assert f'vf-origin-{origin}"' in markup


def test_cards_show_derived_from_only_when_it_exists(container):
    _seed_three_origins(container)

    markup = cards_html(container.catalog.list())

    assert markup.count('class="vf-lineage"') == 1
    assert "derived from <code>designed-one</code>" in markup


def test_cards_carry_language_rate_and_recipe(container):
    container.catalog.register(b"RIFF", slug="imported-one", name="Imported One")

    markup = cards_html(container.catalog.list())

    assert '<span class="vf-chip">Spanish</span>' in markup
    assert '<span class="vf-chip">24,000 Hz</span>' in markup
    assert 'class="vf-recipe"' in markup


def test_cards_escape_catalog_content(container):
    container.catalog.register(
        b"RIFF", slug="hostile", name="<script>alert(1)</script>"
    )

    markup = cards_html(container.catalog.list())

    assert "<script>" not in markup
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in markup


def test_cards_escape_tags(container):
    container.catalog.register(
        b"RIFF", slug="tagged", name="Tagged", tags=["<script>bad()</script>"]
    )

    markup = cards_html(container.catalog.list())

    assert "<script>bad()" not in markup
    assert "&lt;script&gt;bad()&lt;/script&gt;" in markup


def test_non_neutral_reference_is_only_flagged_when_not_neutral(container):
    container.catalog.register(b"RIFF", slug="neutral-one", name="Neutral One")
    container.catalog.register(
        b"RIFF", slug="emotional-one", name="Emotional One", neutral=False
    )

    markup = cards_html(container.catalog.list())

    assert markup.count("non-neutral reference") == 1
    card = markup.split('data-slug="emotional-one"')[1]
    assert "non-neutral reference" in card


def test_lineage_shows_derived_and_timbre_when_they_exist(container):
    container.catalog.register(b"RIFF-base", slug="base-voice", name="Base")
    container.catalog.register(b"RIFF-target", slug="target-voice", name="Target")
    container.derive.derive(
        "base-voice", slug="hybrid", timbre_from="target-voice"
    )
    container.catalog.register(b"RIFF", slug="plain", name="Plain")

    markup = cards_html(container.catalog.list())

    lineage = markup.split('data-slug="hybrid"')[1].split("</article>")[0]
    assert "derived from <code>base-voice</code>" in lineage
    assert "timbre <code>target-voice</code>" in lineage
    plain = markup.split('data-slug="plain"')[1].split("</article>")[0]
    assert "vf-lineage" not in plain


def test_cards_keep_the_reference_transcript_escaped(container):
    container.catalog.register(
        b"RIFF",
        slug="clipped",
        name="Clipped",
        transcript="<b>La casa</b> estaba vacía.",
    )

    markup = cards_html(container.catalog.list())

    assert 'class="vf-transcript"' in markup
    assert "&lt;b&gt;La casa&lt;/b&gt; estaba vacía." in markup


def test_cards_are_ordered_by_name(container):
    for slug, name in (("zulu", "Zulu"), ("alfa", "alfa"), ("mike", "Mike")):
        container.catalog.register(b"RIFF", slug=slug, name=name)

    markup = cards_html(container.catalog.list())

    positions = [markup.index(f'data-slug="{slug}"') for slug in ("alfa", "mike", "zulu")]
    assert positions == sorted(positions)


def test_count_line_is_singular_or_plural(container):
    container.catalog.register(b"RIFF", slug="only-one", name="Only One")

    assert '<p class="vf-count">1 voice</p>' in cards_html(container.catalog.list())

    container.catalog.register(b"RIFF", slug="second", name="Second")
    assert '<p class="vf-count">2 voices</p>' in cards_html(container.catalog.list())


def test_console_css_styles_the_cards_and_badges():
    assert ".vf-cards" in CONSOLE_CSS
    assert ".vf-badge" in CONSOLE_CSS
    assert "grid-template-columns" in CONSOLE_CSS


def test_empty_catalog_says_so():
    markup = cards_html([])

    assert "vf-empty" in markup
    assert "empty" in markup


# ── readiness ───────────────────────────────────────────────────────────
class _DownEngine:
    def status(self):
        return {"status": "down"}


def test_preview_ready_explains_a_down_engine(ctx, container):
    container.catalog.register(b"RIFF", slug="narrador", name="Narrador")

    message = preview_ready(replace(ctx, engine=_DownEngine()), "narrador")

    assert "voice-forge up" in message
    assert "narrador" in message


def test_preview_ready_without_a_voice_asks_for_one(ctx):
    assert "Pick a voice" in preview_ready(ctx, None)


# ── derive ──────────────────────────────────────────────────────────────
def test_derive_creates_the_voice_and_refreshes_the_cards(ctx, container):
    container.catalog.register(b"RIFF-base", slug="base-voice", name="Base")

    cards, message = derive_voice(ctx, "base-voice", "derived-copy", "Derived Copy", -3.0)

    created = container.catalog.get("derived-copy")
    assert created.origin == "derived"
    assert created.recipe["derived_from"] == "base-voice"
    assert "Traceback" not in message
    assert "derived-copy" in message
    assert "derived-copy" in cards
    assert "Derived Copy" in cards
    assert "derived from <code>base-voice</code>" in cards


def test_derive_on_a_taken_slug_is_a_readable_message(ctx, container):
    container.catalog.register(b"RIFF", slug="taken", name="Taken")

    cards, message = derive_voice(ctx, "taken", "taken", None, 0.0)

    assert "already in the catalog" in message
    assert "Traceback" not in message
    assert "taken" in cards


def test_derive_out_of_range_pitch_is_a_readable_message(ctx, container):
    container.catalog.register(b"RIFF", slug="base-voice", name="Base")

    cards, message = derive_voice(ctx, "base-voice", "too-far", None, -9.0)

    assert "pitch shift must be within -6..6" in message
    assert "Traceback" not in message
    assert "too-far" not in cards


def test_derive_by_timbre_ignores_the_pitch_slider(ctx, container):
    container.catalog.register(b"RIFF-base", slug="base-voice", name="Base")
    container.catalog.register(b"RIFF-target", slug="target-voice", name="Target")

    cards, message = derive_voice(
        ctx, "base-voice", "hybrid", None, -6.0, timbre="target-voice"
    )

    created = container.catalog.get("hybrid")
    assert created.recipe["transform"] == "timbre"
    assert created.recipe["timbre_from"] == "target-voice"
    assert "pitch_semitones" not in created.recipe
    assert "timbre of `target-voice`" in message
    assert "timbre_from=target-voice" in cards
    assert "Traceback" not in message


# ── remove ──────────────────────────────────────────────────────────────
def test_remove_deletes_the_voice_from_catalog_and_cards(ctx, container):
    container.catalog.register(b"RIFF", slug="doomed", name="Doomed")

    cards, message = remove_voice(ctx, "doomed")

    with pytest.raises(VoiceNotFound):
        container.catalog.get("doomed")
    assert "doomed" not in cards
    assert "Removed" in message


def test_remove_unknown_slug_is_a_message_not_an_exception(ctx, container):
    cards, message = remove_voice(ctx, "ghost")

    assert "no such voice" in message
    assert "Traceback" not in message
    assert "ghost" not in cards


# ── refresh alias ───────────────────────────────────────────────────────
def test_voices_table_matches_cards_html(ctx, container):
    _seed_three_origins(container)

    assert voices_table(ctx) == cards_html(container.catalog.list())
