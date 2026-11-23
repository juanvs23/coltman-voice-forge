"""Design screen: audition candidates, then register the chosen one.

The console is a client of the same services the two
``/api/voices/design/*`` endpoints call: it auditions through
``CatalogService``, writes the same ``out/candidates`` layout through
``AuditionStore`` and quotes the token to register. No HTTP to itself and no
second backend — which is why a voice registered here writes the same
``voice.json`` as the one-call endpoint.

Every function is pure — ``ctx`` plus primitives in, strings and dicts out — so
the flow is testable without a browser or a model.
"""

from __future__ import annotations

import html
from typing import Mapping, Sequence

from ....application.audition_store import Audition
from ....application.catalog_service import emotional_words
from ....domain.errors import VoiceForgeError
from ....domain.models import VoiceBrief
from .context import UiContext, recipe_text
from .voices import cards_html

DESIGN_TIMEOUT_S = 1800


# ── audition ────────────────────────────────────────────────────────────
def design_candidates(
    ctx: UiContext,
    description: str | None,
    language: str | None,
    count: int | None,
    seed: int | None,
    preview_text: str | None,
    emotional: bool,
) -> tuple[str, dict, str]:
    """Generate candidates and leave them playable.

    Returns ``(message, state, candidates_html)``. The state is exactly the
    payload the API returns — a token plus one entry per candidate — so the
    register step never needs anything else.
    """
    text = (description or "").strip()
    if not text:
        return (
            "Write the description of the voice you want.",
            {},
            candidates_html([]),
        )

    try:
        wanted = int(count) if count is not None else 2
        wanted_seed = int(seed) if seed is not None else None
        brief = VoiceBrief(
            description=text,
            language=(language or "Spanish").strip() or "Spanish",
            candidates=wanted,
            seed=wanted_seed,
            preview_text=(preview_text or "").strip() or None,
        )
    except (VoiceForgeError, TypeError, ValueError) as exc:
        return f"Those settings were rejected: {exc}", {}, candidates_html([])

    found = emotional_words(brief.description)
    if found and not emotional:
        return _neutral_message(found), {}, candidates_html([])

    try:
        job = ctx.queue.submit(
            "design",
            lambda: _audition(ctx, brief, emotional),
        )
        finished = ctx.queue.wait(job.id, timeout=DESIGN_TIMEOUT_S)
    except RuntimeError as exc:  # a closed or full queue
        return f"The queue refused the job: {exc}", {}, candidates_html([])

    if finished.state != "done":
        return _failure_message(finished.error), {}, candidates_html([])

    audition: Audition = finished.result
    payload = audition.payload()
    message = (
        f"{len(audition.candidates)} candidates for «{brief.description}». "
        "Listen to them, pick one and register it."
    )
    return message, payload, candidates_html(payload["candidates"])


def _audition(ctx: UiContext, brief: VoiceBrief, emotional: bool) -> Audition:
    """Model work, then the same files the API writes."""
    candidates = ctx.catalog.audition(brief, neutral=not emotional)
    return ctx.auditions.save(brief, candidates, emotional=emotional)


# ── candidates ──────────────────────────────────────────────────────────
def candidates_html(entries: Sequence[Mapping[str, object]] | None) -> str:
    """One player per candidate, with its index and a short recipe."""
    entries = list(entries or [])
    if not entries:
        return (
            '<p class="vf-empty">No candidates yet. Generate them from a '
            "description first.</p>"
        )
    blocks = [_candidate_block(entry) for entry in entries]
    return '<div class="vf-candidates">' + "".join(blocks) + "</div>"


def _candidate_block(entry: Mapping[str, object]) -> str:
    index = entry.get("index")
    rate = entry.get("sample_rate")
    rate_text = f"{int(rate):,} Hz" if isinstance(rate, int) else "unknown rate"
    url = html.escape(str(entry.get("url") or ""))
    recipe = html.escape(recipe_text(entry.get("recipe") or {}, limit=160))
    return (
        f'<article class="vf-candidate" data-index="{html.escape(str(index))}">'
        f'\n  <h4 class="vf-candidate-title">candidate {html.escape(str(index))}'
        f" · {rate_text}</h4>"
        f'\n  <p class="vf-candidate-recipe">{recipe}</p>'
        f'\n  <audio controls preload="none" src="{url}"></audio>'
        f"\n</article>"
    )


# ── register ────────────────────────────────────────────────────────────
def register_choice(
    ctx: UiContext,
    state: Mapping[str, object] | str | None,
    pick: int | str | None,
    slug: str | None,
    name: str | None,
    tags: Sequence[str] | str | None,
    emotional: bool,
) -> tuple[str, str]:
    """Register the chosen candidate. Returns (message, refreshed cards)."""
    cards = cards_html(ctx.catalog.list())
    token = str((state or {}).get("token") or "") if isinstance(state, Mapping) else ""
    if not token:
        return "Generate candidates first, then pick one.", cards

    target = (slug or "").strip()
    if not target:
        return "Type a slug for the voice before registering.", cards

    try:
        index = int(pick) if pick is not None and pick != "" else 0
    except (TypeError, ValueError):
        return f"Candidate index must be a whole number, got {pick!r}.", cards

    try:
        audition = ctx.auditions.load(token)
    except (VoiceForgeError, OSError) as exc:
        return (
            f"Those candidates are gone ({exc}). Generate them again.",
            cards,
        )

    if not 0 <= index < len(audition.candidates):
        return (
            f"Pick a candidate within 0..{len(audition.candidates) - 1}.",
            cards,
        )

    found = emotional_words(audition.brief.description)
    if found and not emotional:
        return _neutral_message(found), cards

    try:
        voice = ctx.catalog.register_candidate(
            audition.candidates[index],
            brief=audition.brief,
            slug=target,
            name=(name or "").strip() or None,
            pick=index,
            tags=_tags(tags),
            neutral=not emotional,
            total=len(audition.candidates),
        )
    except (VoiceForgeError, OSError) as exc:
        return f"Could not register `{target}`: {exc}", cards
    return (
        f"Registered `{voice.slug}` from candidate {index} ({voice.sample_rate:,} Hz). "
        "The clip is immutable: a new voice means a new slug.",
        cards_html(ctx.catalog.list()),
    )


def _neutral_message(found: Sequence[str]) -> str:
    words = ", ".join(f"`{word}`" for word in found)
    return (
        f"The description carries emotion ({words}), but a catalog voice must be "
        "neutral: emotion belongs to each line. Remove those words, or tick "
        '"Accept a non-neutral reference" to keep them.'
    )


def _tags(value: Sequence[str] | str | None) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        value = value.split(",")
    return tuple(part.strip() for part in value if part and part.strip())


def _failure_message(error: str | None) -> str:
    reason = error or "the audition did not finish"
    if "EngineUnavailable" in reason:
        return f"The engine is down; run `voice-forge up` and try again — {reason}"
    if "ValidationError:" in reason:
        return reason.split("ValidationError:", 1)[1].strip()
    return f"The audition failed: {reason}"
