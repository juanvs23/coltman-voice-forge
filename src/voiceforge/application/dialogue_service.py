"""Use case: render a dialogue into a single mastered file."""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path
from typing import Sequence

from ..domain.errors import RenderFailed, ValidationError
from ..domain.models import Dialogue, RenderResult
from .ports import AudioAssembler, CatalogRepository, SpeechSynthesizer


class DialogueService:
    def __init__(
        self,
        catalog: CatalogRepository,
        synthesizer: SpeechSynthesizer,
        assembler: AudioAssembler,
        workdir: Path,
    ) -> None:
        self._catalog = catalog
        self._synth = synthesizer
        self._assembler = assembler
        self._workdir = Path(workdir)

    def render(
        self,
        dialogue: Dialogue,
        out_path: Path,
        *,
        target_lufs: float | None = -14.0,
    ) -> RenderResult:
        out_path = Path(out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)

        # Fail before spending GPU time on an unknown voice.
        voices = {}
        for slug in dialogue.speakers:
            try:
                voices[slug] = self._catalog.get(slug)
            except Exception as exc:  # noqa: BLE001 - re-raise with context
                raise ValidationError(
                    f"line references an unknown voice: {slug}"
                ) from exc

        self._workdir.mkdir(parents=True, exist_ok=True)
        segments: list[tuple[Path, int]] = []

        with tempfile.TemporaryDirectory(dir=self._workdir, prefix="render-") as tmp:
            tmp_dir = Path(tmp)
            for index, line in enumerate(dialogue.lines):
                line_path = tmp_dir / f"line-{index:04d}.wav"
                duration = self._synth.synthesize(
                    text=line.text,
                    voice=voices[line.voice],
                    emotion=line.emotion,
                    speed=line.speed,
                    out_path=line_path,
                )
                if not line_path.exists() or duration <= 0:
                    raise RenderFailed(
                        f"line {index} produced no audio for voice {line.voice}"
                    )
                segments.append((line_path, line.pause_after_ms))

            produced, duration = self._assembler.assemble(
                segments, out_path, target_lufs
            )

        if not produced.exists():
            raise RenderFailed("the assembler reported success but wrote no file")

        return RenderResult(
            path=produced,
            duration_s=duration,
            lines=len(dialogue.lines),
            speakers=dialogue.speakers,
        )
