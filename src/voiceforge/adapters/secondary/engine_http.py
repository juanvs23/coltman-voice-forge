"""HTTP client for the model host.

This is the seam. Everything model-specific lives on the other side of this
file: swap Qwen3-TTS for IndexTTS and the core never notices.
"""

from __future__ import annotations

import base64
from pathlib import Path
from typing import Mapping, Sequence

import httpx

from ...domain.errors import EngineUnavailable
from ...domain.models import (
    DesignCandidate,
    Emotion,
    Voice,
    VoiceBrief,
)


class HttpEngine:
    def __init__(self, base_url: str, timeout_s: float = 900.0) -> None:
        self.base_url = base_url.rstrip("/")
        self._timeout = timeout_s

    # ── ports ───────────────────────────────────────────────────────────
    def design(self, brief: VoiceBrief) -> Sequence[DesignCandidate]:
        payload = {
            "description": brief.description,
            "language": brief.language,
            "candidates": brief.candidates,
            "seed": brief.seed,
            "preview_text": brief.preview_text,
        }
        data = self._post("/design", payload)
        candidates = []
        for item in data.get("candidates", []):
            candidates.append(
                DesignCandidate(
                    index=int(item["index"]),
                    audio=base64.b64decode(item["audio_b64"]),
                    sample_rate=int(item.get("sample_rate", 24_000)),
                    recipe=item.get("recipe", {}),
                )
            )
        return candidates

    def synthesize(
        self,
        *,
        text: str,
        voice: Voice,
        emotion: Emotion,
        speed: float,
        out_path: Path,
    ) -> float:
        payload = {
            "text": text,
            "ref_audio": str(voice.ref_audio),
            "ref_transcript": voice.ref_transcript,
            "language": voice.language,
            "emotion": {
                "axes": {axis.value: value for axis, value in emotion.normalised().axes.items()},
                "intensity": emotion.intensity,
                "hint": emotion.hint,
            },
            "speed": speed,
            "out_path": str(out_path),
        }
        data = self._post("/synthesize", payload)
        return float(data.get("duration", 0.0))

    # ── diagnostics ─────────────────────────────────────────────────────
    def health(self) -> Mapping[str, object]:
        return self._request("GET", "/health")

    def warm(self, modes: Sequence[str] | None = None) -> Mapping[str, object]:
        return self._post("/warm", {"modes": list(modes or ["design", "speech"])})

    def shutdown(self) -> Mapping[str, object]:
        return self._post("/shutdown", {})

    # ── internals ───────────────────────────────────────────────────────
    def _post(self, path: str, payload: Mapping[str, object]) -> Mapping[str, object]:
        return self._request("POST", path, json=dict(payload))

    def _request(self, method: str, path: str, **kwargs) -> Mapping[str, object]:
        try:
            with httpx.Client(base_url=self.base_url, timeout=self._timeout) as client:
                response = client.request(method, path, **kwargs)
                response.raise_for_status()
                return response.json()
        except httpx.HTTPError as exc:
            raise EngineUnavailable(
                f"model host at {self.base_url} did not answer {path}: {exc}"
            ) from exc
