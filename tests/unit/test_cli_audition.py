"""Audition and register-candidate from the CLI: no Gradio, no engine.

The CLI mirrors the two ``/api/voices/design/*`` endpoints: ``audition`` leaves
the candidates in ``out/candidates`` and prints the token, ``register-candidate``
quotes that token to write one ``voice.json``. These tests drive the parsed
arguments and ``args.func``, so the real commands run against the fakes.
"""

from __future__ import annotations

import json
import re

import pytest

from voiceforge.adapters.primary.cli import build_parser
from voiceforge.application.catalog_service import emotional_words
from voiceforge.domain.errors import ValidationError, VoiceNotFound

DESCRIPTION = "narrador grave y pausado"
TOKEN_RE = re.compile(r"^token: ([0-9a-f]{12})$", re.MULTILINE)


def _run(container, capsys, argv):
    args = build_parser().parse_args(argv)
    code = args.func(container, args)
    return code, capsys.readouterr().out


def _audition(container, capsys, *extra):
    return _run(
        container,
        capsys,
        ["audition", DESCRIPTION, "--candidates", "3", *extra],
    )


def _token(output: str) -> str:
    match = TOKEN_RE.search(output)
    assert match is not None, output
    return match.group(1)


def _directory(container):
    return container.settings.out_dir / "candidates"


# ── audition ────────────────────────────────────────────────────────────
def test_audition_writes_the_candidates_and_prints_the_token(container, capsys):
    code, output = _audition(container, capsys)

    assert code == 0
    token = _token(output)
    directory = _directory(container)
    sidecar = json.loads((directory / f"{token}.json").read_text(encoding="utf-8"))
    assert sidecar["token"] == token
    assert sidecar["brief"]["description"] == DESCRIPTION
    assert len(list(directory.glob(f"{token}-*.wav"))) == 3

    candidate_lines = [line for line in output.splitlines() if re.match(r"^  \d  /", line)]
    assert len(candidate_lines) == 3
    for index, line in enumerate(candidate_lines):
        assert str((directory / f"{token}-{index}.wav").resolve()) in line
        assert "24000 Hz" in line
        assert f"instruct={DESCRIPTION}" in line
    assert f"voice-forge register-candidate {token}" in output


def test_a_second_audition_replaces_the_first(container, capsys):
    _, first_output = _audition(container, capsys)
    first = _token(first_output)
    _, second_output = _audition(container, capsys)
    second = _token(second_output)

    directory = _directory(container)
    assert sorted(path.name for path in directory.iterdir()) == sorted(
        [f"{second}-0.wav", f"{second}-1.wav", f"{second}-2.wav", f"{second}.json"]
    )
    assert not (directory / f"{first}-0.wav").exists()


def test_an_emotional_word_without_the_flag_is_rejected(container, capsys):
    with pytest.raises(ValidationError) as caught:
        _run(container, capsys, ["audition", "una narradora triste", "--candidates", "2"])

    word = emotional_words("una narradora triste")[0]
    message = str(caught.value)
    assert word in message
    assert "neutral" in message
    assert not _directory(container).exists()


# ── register-candidate ──────────────────────────────────────────────────
def test_register_candidate_registers_the_pick(container, capsys):
    _, audition_output = _audition(container, capsys)
    token = _token(audition_output)

    code, output = _run(
        container,
        capsys,
        ["register-candidate", token, "--pick", "1", "--slug", "cli-pick"],
    )

    assert code == 0
    voice = container.catalog.get("cli-pick")
    assert voice.origin == "designed"
    assert voice.recipe["candidates"] == 3
    assert voice.recipe["picked"] == 1
    assert voice.reference_neutral is True
    assert "cli-pick" in [item.slug for item in container.catalog.list()]
    assert "registered: cli-pick" in output
    assert "origin=designed" in output
    assert str(voice.ref_audio) in output
    assert f"instruct={DESCRIPTION}" in output


def test_an_emotional_audition_keeps_its_flag_at_register(container, capsys):
    description = "una narradora triste y serena"
    _, audition_output = _run(
        container,
        capsys,
        ["audition", description, "--candidates", "2", "--emotional"],
    )
    token = _token(audition_output)

    _run(container, capsys, ["register-candidate", token, "--slug", "triste-voz"])

    assert container.catalog.get("triste-voz").reference_neutral is False


def test_an_unknown_token_is_not_found(container, capsys):
    with pytest.raises(VoiceNotFound):
        _run(container, capsys, ["register-candidate", "0123456789ab", "--slug", "ghost"])


def test_a_pick_outside_the_audition_is_rejected(container, capsys):
    _, audition_output = _audition(container, capsys)
    token = _token(audition_output)

    with pytest.raises(ValidationError):
        _run(
            container,
            capsys,
            ["register-candidate", token, "--pick", "9", "--slug", "too-far"],
        )

    with pytest.raises(VoiceNotFound):
        container.catalog.get("too-far")
