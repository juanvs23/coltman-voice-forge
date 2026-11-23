"""Ports: the contracts the outside world must satisfy.

If a provider cannot implement one of these, it is the wrong provider — not a
reason to change the contract.
"""

from __future__ import annotations

from pathlib import Path
from typing import Mapping, Protocol, Sequence

from ..domain.models import (
    DesignCandidate,
    Emotion,
    NewVoice,
    RenderResult,
    Voice,
    VoiceBrief,
)


class CatalogRepository(Protocol):
    """Persistence of the voice catalog. One directory per voice."""

    def save(self, new: NewVoice, audio: bytes) -> Voice: ...

    def list(self) -> Sequence[Voice]: ...

    def get(self, slug: str) -> Voice: ...

    def remove(self, slug: str) -> None: ...

    def verify(self) -> Sequence[dict]: ...


class VoiceDesigner(Protocol):
    """Create a voice from a text description. No reference audio involved."""

    def design(self, brief: VoiceBrief) -> Sequence[DesignCandidate]: ...


class SpeechSynthesizer(Protocol):
    """Turn text into audio for a catalog voice, with emotional direction."""

    def synthesize(
        self,
        *,
        text: str,
        voice: Voice,
        emotion: Emotion,
        speed: float,
        out_path: Path,
    ) -> float:
        """Write a wav to ``out_path`` and return its duration in seconds."""
        ...


class AudioAssembler(Protocol):
    """Join rendered lines into one file, with pauses and optional loudness."""

    def assemble(
        self,
        segments: Sequence[tuple[Path, int]],
        out_path: Path,
        target_lufs: float | None,
    ) -> tuple[Path, float]: ...


class VoiceTransformer(Protocol):
    """Derive a new voice from an existing reference, without touching it."""

    def pitch(self, source: Path, out_path: Path, semitones: float) -> None: ...


class TimbreTransformer(Protocol):
    """Move a reference toward another voice's timbre, keeping its performance.

    This is a different operation from ``VoiceTransformer.pitch``: pitch moves
    the same identity up or down, timbre borrows the identity of a second clip.
    """

    def timbre(self, source: Path, target_ref: Path, out_path: Path) -> None: ...


class JobState(Protocol):
    """Cross-process visibility of the one running model job.

    The queue itself is in-process, but a render started by one CLI must be
    visible to ``down``/``queue`` started by another. This port is the shared
    truth, with no IPC protocol and no daemon: whoever runs a job announces it,
    everyone else can ask. Implementations keep the announcement alive for the
    whole job, so a crashed worker cannot leave it behind as truth.
    """

    def begin(self, kind: str, job_id: str, pid: int) -> None: ...

    def end(self) -> None: ...

    def current(self) -> dict | None: ...


class EngineControl(Protocol):
    """Lifecycle of the model host: up, warm, status, down."""

    def up(self) -> Mapping[str, object]: ...

    def warm(self, modes: Sequence[str] | None = None) -> Mapping[str, object]: ...

    def status(self) -> Mapping[str, object]: ...

    def down(self) -> Mapping[str, object]: ...
