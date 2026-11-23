"""Dialogue script parsing.

The on-disk format is YAML because operators edit it by hand. Parsing lives in
the domain: it is a rule, not an adapter.

A long script is split on ``## chapter: name`` lines **before** the YAML is
parsed. That marker is a YAML comment, so ``yaml.safe_load`` would erase it:
splitting the raw text is the only way to keep it. Everything before the first
marker is the script header, which may only carry global keys (``title``).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Mapping

import yaml

from .errors import ValidationError
from .models import Chapter, Dialogue, Emotion, EmotionAxis, Line

CHAPTER_MARKER = re.compile(r"^\s*##\s*chapter\b\s*:?\s*(.*)$", re.IGNORECASE)


def _emotion(raw: Any) -> Emotion:
    if raw is None:
        return Emotion()
    if isinstance(raw, str):
        return Emotion(hint=raw)
    if not isinstance(raw, Mapping):
        raise ValidationError("emotion must be a mapping of axis -> 0..1, or a text hint")

    axes: dict[EmotionAxis, float] = {}
    intensity = 0.6
    hint: str | None = None
    for key, value in raw.items():
        if key == "intensity":
            intensity = float(value)
        elif key == "hint":
            hint = str(value)
        else:
            try:
                axes[EmotionAxis(str(key))] = float(value)
            except ValueError as exc:  # unknown axis
                allowed = ", ".join(a.value for a in EmotionAxis)
                raise ValidationError(f"unknown emotion axis {key!r}; allowed: {allowed}") from exc
    return Emotion(axes=axes, intensity=intensity, hint=hint)


def parse_dialogue(
    data: Mapping[str, Any], *, base_dir: Path | None = None
) -> Dialogue:
    """Build a :class:`Dialogue` from already-parsed YAML data.

    ``base_dir`` is stored on the dialogue so a relative ``source:`` path can be
    resolved later; it is the script's folder when loaded from disk and ``None``
    for text that arrived over the API.
    """

    lines_raw = data.get("lines")
    if not isinstance(lines_raw, list) or not lines_raw:
        raise ValidationError("a script needs a non-empty 'lines' list")

    lines: list[Line] = []
    for position, raw in enumerate(lines_raw, start=1):
        if not isinstance(raw, Mapping):
            raise ValidationError(f"line {position} must be a mapping")
        try:
            voice = str(raw["voice"]).strip()
        except KeyError as exc:
            raise ValidationError(f"line {position} is missing 'voice'") from exc
        text = raw.get("text")
        source = raw.get("source")
        try:
            lines.append(
                Line(
                    voice=voice,
                    text=None if text is None else str(text).strip(),
                    source=None if source is None else str(source).strip(),
                    emotion=_emotion(raw.get("emotion")),
                    speed=float(raw.get("speed", 1.0)),
                    pause_after_ms=int(raw.get("pause_after_ms", 350)),
                )
            )
        except ValidationError as exc:
            raise ValidationError(f"line {position}: {exc}") from exc

    return Dialogue(
        title=str(data.get("title", "untitled")).strip() or "untitled",
        lines=tuple(lines),
        base_dir=None if base_dir is None else Path(base_dir),
    )


def load_dialogue(path) -> Dialogue:
    path = Path(path)
    with open(path, "r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    if not isinstance(data, Mapping):
        raise ValidationError("the script root must be a mapping")
    return parse_dialogue(data, base_dir=path.parent)


def split_chapter_blocks(text: str) -> tuple[str, list[tuple[str | None, str]]]:
    """Split raw script text into a header and one block per chapter marker.

    Returns ``(header, blocks)`` where each block is ``(marker_name, yaml_text)``
    and ``marker_name`` is ``None`` when the marker carried no name. The marker
    line itself is dropped; the blocks keep their original text verbatim,
    newlines included, so YAML block scalars still parse.
    """

    header_lines: list[str] = []
    blocks: list[tuple[str | None, str]] = []
    current_name: str | None = None
    current: list[str] | None = None

    for line in text.splitlines(keepends=True):
        match = CHAPTER_MARKER.match(line)
        if match is not None:
            if current is None:
                header = "".join(header_lines)
            else:
                blocks.append((current_name, "".join(current)))
            current_name = match.group(1).strip() or None
            current = []
            continue
        if current is None:
            header_lines.append(line)
        else:
            current.append(line)

    if current is None:
        header = "".join(header_lines)
    else:
        blocks.append((current_name, "".join(current)))
    return header, blocks


def _yaml_mapping(text: str, where: str) -> dict[str, Any]:
    try:
        data = yaml.safe_load(text) or {}
    except yaml.YAMLError as exc:
        raise ValidationError(f"{where} is not valid YAML: {exc}") from exc
    if not isinstance(data, Mapping):
        raise ValidationError(f"{where} must be a mapping")
    return dict(data)


def parse_chapters(text: str, *, base_dir: Path | None = None) -> list[Chapter]:
    """Parse a long script into chapters, split on the raw-text marker.

    No marker means one chapter with the whole document, which keeps every
    existing single-file script working unchanged. Text before the first marker
    is the header and may only set global keys; carrying ``lines`` there is an
    error because those lines would have no chapter name. ``base_dir`` is
    forwarded to every dialogue so relative ``source:`` paths resolve against
    the script's folder.
    """

    header, blocks = split_chapter_blocks(text)
    header_data = _yaml_mapping(header, "the script header")

    if not blocks:
        return [
            Chapter(
                name="chapter 1",
                dialogue=parse_dialogue(header_data, base_dir=base_dir),
            )
        ]

    if "lines" in header_data:
        raise ValidationError(
            "the script header before the first '## chapter:' marker cannot contain "
            "'lines'; move those lines under a chapter marker"
        )
    unknown = sorted(set(header_data) - {"title"})
    if unknown:
        raise ValidationError(
            "the script header may only set 'title'; found: " + ", ".join(unknown)
        )

    script_title = header_data.get("title")
    chapters: list[Chapter] = []
    for index, (marker_name, block) in enumerate(blocks, start=1):
        name = marker_name or f"chapter {index}"
        data = _yaml_mapping(block, f"chapter {name!r}")
        if not data.get("lines"):
            raise ValidationError(f"chapter {name!r} needs a non-empty 'lines' list")
        if script_title and "title" not in data:
            data["title"] = script_title
        try:
            dialogue = parse_dialogue(data, base_dir=base_dir)
        except ValidationError as exc:
            raise ValidationError(f"chapter {name!r}: {exc}") from exc
        chapters.append(Chapter(name=name, dialogue=dialogue))
    return chapters


def load_chapters(path) -> list[Chapter]:
    path = Path(path)
    with open(path, "r", encoding="utf-8") as handle:
        return parse_chapters(handle.read(), base_dir=path.parent)
