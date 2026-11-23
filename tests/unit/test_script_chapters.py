"""Chapter parsing: the marker is a YAML comment, so splitting is textual."""

from __future__ import annotations

import pytest

from voiceforge.domain.errors import ValidationError
from voiceforge.domain.script import (
    load_chapters,
    parse_chapters,
    split_chapter_blocks,
)

TWO_CHAPTERS = """\
title: saga
## chapter: la casa
lines:
  - {voice: narrador-terror, text: "La casa estaba vacía."}
## chapter: el pasillo
lines:
  - {voice: narrador-energico, text: "Alguien encendió la luz."}
"""


def test_two_markers_split_into_a_header_and_two_blocks():
    header, blocks = split_chapter_blocks(TWO_CHAPTERS)

    assert header.strip() == "title: saga"
    assert [name for name, _ in blocks] == ["la casa", "el pasillo"]
    # Three groups reach the parser: the header plus the two marked blocks.
    assert len(blocks) + (1 if header.strip() else 0) == 3


def test_two_markers_parse_into_two_chapters():
    chapters = parse_chapters(TWO_CHAPTERS)

    assert [chapter.name for chapter in chapters] == ["la casa", "el pasillo"]
    assert [len(chapter.dialogue.lines) for chapter in chapters] == [1, 1]
    # The header title is inherited by chapters that do not set their own.
    assert [chapter.dialogue.title for chapter in chapters] == ["saga", "saga"]


def test_marker_without_a_name_uses_its_position():
    text = """\
## chapter:
lines:
  - {voice: narrador-terror, text: "Uno."}
## chapter:
lines:
  - {voice: narrador-terror, text: "Dos."}
"""

    chapters = parse_chapters(text)

    assert [chapter.name for chapter in chapters] == ["chapter 1", "chapter 2"]


def test_marker_is_case_insensitive_and_the_colon_is_optional():
    text = """\
## Chapter la casa
lines:
  - {voice: narrador-terror, text: "Uno."}
##CHAPTER: el pasillo
lines:
  - {voice: narrador-terror, text: "Dos."}
"""

    assert [chapter.name for chapter in parse_chapters(text)] == ["la casa", "el pasillo"]


def test_block_without_lines_names_the_chapter():
    text = """\
## chapter: uno
lines:
  - {voice: narrador-terror, text: "Uno."}
## chapter: dos vacio
title: nada
"""

    with pytest.raises(ValidationError, match="dos vacio"):
        parse_chapters(text)


def test_lines_before_the_first_marker_are_an_error():
    text = """\
title: saga
lines:
  - {voice: narrador-terror, text: "Sin capítulo."}
## chapter: uno
lines:
  - {voice: narrador-terror, text: "Uno."}
"""

    with pytest.raises(ValidationError, match="header"):
        parse_chapters(text)


def test_unknown_header_keys_are_an_error():
    text = """\
title: saga
speed: 1.2
## chapter: uno
lines:
  - {voice: narrador-terror, text: "Uno."}
"""

    with pytest.raises(ValidationError, match="speed"):
        parse_chapters(text)


def test_no_marker_is_one_chapter():
    text = """\
title: dialogo corto
lines:
  - {voice: narrador-terror, text: "La casa estaba vacía."}
"""

    chapters = parse_chapters(text)

    assert len(chapters) == 1
    assert chapters[0].name == "chapter 1"
    assert chapters[0].dialogue.title == "dialogo corto"


def test_load_chapters_reads_the_file(tmp_path):
    path = tmp_path / "guion.yaml"
    path.write_text(TWO_CHAPTERS, encoding="utf-8")

    assert [chapter.name for chapter in load_chapters(path)] == ["la casa", "el pasillo"]
