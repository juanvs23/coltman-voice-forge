"""Shared fakes. No GPU, no torch, no network."""

from __future__ import annotations

from pathlib import Path
from typing import Sequence

import pytest

from voiceforge.adapters.secondary.ffmpeg_assembler import FfmpegAssembler
from voiceforge.adapters.secondary.fs_catalog import FileCatalog
from voiceforge.application.catalog_service import CatalogService
from voiceforge.application.dialogue_service import DialogueService
from voiceforge.container import Container
from voiceforge.domain.models import DesignCandidate, Emotion, Voice, VoiceBrief
from voiceforge.config import Settings


class FakeDesigner:
    def __init__(self, sample_rate: int = 24_000) -> None:
        self.sample_rate = sample_rate
        self.calls: list[VoiceBrief] = []

    def design(self, brief: VoiceBrief) -> Sequence[DesignCandidate]:
        self.calls.append(brief)
        return [
            DesignCandidate(
                index=index,
                audio=f"RIFF-fake-{index}".encode(),
                sample_rate=self.sample_rate,
                recipe={"model": "fake-designer", "instruct": brief.description},
            )
            for index in range(brief.candidates)
        ]


class FakeSynthesizer:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, Emotion, float]] = []

    def synthesize(self, *, text, voice: Voice, emotion, speed, out_path: Path) -> float:
        self.calls.append((text, voice.slug, emotion, speed))
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(b"RIFF-fake-line")
        return 1.0


class FakeAssembler:
    def __init__(self) -> None:
        self.calls: list[tuple[list[tuple[Path, int]], Path, float | None]] = []

    def assemble(self, segments, out_path, target_lufs):
        self.calls.append((list(segments), Path(out_path), target_lufs))
        Path(out_path).parent.mkdir(parents=True, exist_ok=True)
        Path(out_path).write_bytes(b"RIFF-fake-mix")
        return Path(out_path), 12.5


class FakeEngine:
    def up(self):
        return {"status": "up"}

    def warm(self, modes=None):
        return {"loaded": list(modes or [])}

    def status(self):
        return {"status": "up", "models": {}}

    def down(self):
        return {"status": "down"}


@pytest.fixture
def clock():
    return lambda: "2026-11-20T00:00:00+00:00"


@pytest.fixture
def catalog_dir(tmp_path: Path) -> Path:
    return tmp_path / "catalog"


@pytest.fixture
def repository(catalog_dir: Path) -> FileCatalog:
    return FileCatalog(catalog_dir)


@pytest.fixture
def designer() -> FakeDesigner:
    return FakeDesigner()


@pytest.fixture
def catalog_service(repository, designer, clock) -> CatalogService:
    return CatalogService(repository, designer, clock)


@pytest.fixture
def synthesizer() -> FakeSynthesizer:
    return FakeSynthesizer()


@pytest.fixture
def assembler() -> FakeAssembler:
    return FakeAssembler()


@pytest.fixture
def dialogue_service(repository, synthesizer, assembler, tmp_path) -> DialogueService:
    return DialogueService(repository, synthesizer, assembler, tmp_path / "work")


@pytest.fixture
def container(catalog_service, dialogue_service, tmp_path) -> Container:
    settings = Settings(
        catalog_dir=tmp_path / "catalog",
        out_dir=tmp_path / "out",
        work_dir=tmp_path / "work",
    ).normalised()
    return Container(
        settings=settings,
        catalog=catalog_service,
        dialogue=dialogue_service,
        engine=FakeEngine(),
    )


@pytest.fixture
def ffmpeg_assembler() -> FfmpegAssembler:
    return FfmpegAssembler()
