"""Chaptered rendering: one file per chapter, each measured after mastering."""

from __future__ import annotations

from voiceforge.adapters.primary.cli import build_parser
from voiceforge.domain.models import VoiceBrief
from voiceforge.domain.script import parse_chapters

THREE_CHAPTERS = """\
title: saga de prueba
## chapter: la casa
lines:
  - {voice: narrador-terror, text: "La casa estaba vacía."}
  - {voice: narrador-terror, text: "Nadie recordaba quién vivió allí."}
## chapter: el pasillo
lines:
  - {voice: narrador-energico, text: "Alguien encendió la luz."}
## chapter: el cierre
lines:
  - {voice: narradora-ming, text: "No había nadie."}
"""

VOICES = ("narrador-terror", "narrador-energico", "narradora-ming")


def _catalog(catalog_service) -> None:
    for slug in VOICES:
        catalog_service.design(VoiceBrief(description=slug), slug=slug, name=slug)


def test_render_chapters_writes_one_file_per_chapter(
    catalog_service, dialogue_service, assembler, tmp_path
):
    _catalog(catalog_service)
    chapters = parse_chapters(THREE_CHAPTERS)
    out_dir = tmp_path / "out"

    results = dialogue_service.render_chapters(chapters, out_dir, "narracion")

    assert [result.path.name for result in results] == [
        "narracion-01.wav",
        "narracion-02.wav",
        "narracion-03.wav",
    ]
    assert [result.name for result in results] == ["la casa", "el pasillo", "el cierre"]
    assert [result.lines for result in results] == [2, 1, 1]
    assert all(result.path.exists() for result in results)
    assert [result.lufs for result in results] == [-14.0, -14.0, -14.0]
    assert [result.duration_s for result in results] == [12.5, 12.5, 12.5]
    assert [path.name for path in assembler.measured] == [
        "narracion-01.wav",
        "narracion-02.wav",
        "narracion-03.wav",
    ]


def test_render_chapters_leaves_no_debris_in_the_output_directory(
    catalog_service, dialogue_service, tmp_path
):
    _catalog(catalog_service)
    out_dir = tmp_path / "out"

    dialogue_service.render_chapters(parse_chapters(THREE_CHAPTERS), out_dir, "narracion")

    assert sorted(path.name for path in out_dir.iterdir()) == [
        "narracion-01.wav",
        "narracion-02.wav",
        "narracion-03.wav",
    ]


def test_render_chapters_without_mastering_reports_no_loudness(
    catalog_service, dialogue_service, assembler, tmp_path
):
    _catalog(catalog_service)

    results = dialogue_service.render_chapters(
        parse_chapters(THREE_CHAPTERS), tmp_path / "out", "narracion", target_lufs=None
    )

    assert [result.lufs for result in results] == [None, None, None]
    assert assembler.measured == []


def test_cli_render_chapter_prints_each_file_and_a_total(container, capsys, tmp_path):
    for slug in VOICES:
        container.catalog.design(VoiceBrief(description=slug), slug=slug, name=slug)
    script = tmp_path / "guion.yaml"
    script.write_text(THREE_CHAPTERS, encoding="utf-8")
    out = tmp_path / "out" / "narracion.wav"

    args = build_parser().parse_args(
        ["render", str(script), "--out", str(out), "--chapter"]
    )
    code = args.func(container, args)
    printed = capsys.readouterr().out

    assert code == 0
    assert "narracion-01.wav" in printed
    assert "narracion-03.wav" in printed
    assert printed.count("LUFS") == 3
    assert "total  3 chapters" in printed
