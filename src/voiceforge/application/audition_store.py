"""Auditions of design candidates on disk.

The REST API and the console must agree on where a candidate lives, so the
layout is defined once, here, and both adapters use it:

    out/candidates/<token>-<index>.wav
    out/candidates/<token>.json      the brief that produced them

Storage policy: **one live audition at a time.** Saving a new audition removes
every file the previous one left, so the directory has a constant size no
matter how many experiments the operator runs. A candidate is disposable until
it is registered; the token is what a later request quotes to register it.

Nothing here trusts a client: the wav path is rebuilt from the token and the
index, never read back from the sidecar, and the token must match the one the
sidecar was written with.
"""

from __future__ import annotations

import json
import re
import secrets
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from ..domain.errors import ValidationError, VoiceNotFound
from ..domain.models import DesignCandidate, VoiceBrief

# 12 lowercase hex characters: short enough to quote, long enough to collide
# only by accident.
TOKEN_RE = re.compile(r"^[0-9a-f]{12}$")


@dataclass(frozen=True)
class Audition:
    """The candidates one brief produced, with the brief that produced them."""

    token: str
    brief: VoiceBrief
    emotional: bool
    candidates: tuple[DesignCandidate, ...]

    def payload(self) -> dict:
        """The shape the API returns and the console keeps as its state."""
        return {
            "token": self.token,
            "candidates": [
                {
                    "index": candidate.index,
                    "url": f"/candidates/{self.token}-{candidate.index}.wav",
                    "sample_rate": candidate.sample_rate,
                    "recipe": dict(candidate.recipe),
                }
                for candidate in self.candidates
            ],
        }


class AuditionStore:
    def __init__(self, out_dir: Path) -> None:
        self.directory = Path(out_dir) / "candidates"

    # ── write ───────────────────────────────────────────────────────────
    def save(
        self,
        brief: VoiceBrief,
        candidates: Sequence[DesignCandidate],
        *,
        emotional: bool = False,
    ) -> Audition:
        """Write one audition, replacing whatever the previous one left."""
        candidates = tuple(candidates)
        if not candidates:
            raise ValidationError("an audition needs at least one candidate")

        token = secrets.token_hex(6)
        self.directory.mkdir(parents=True, exist_ok=True)
        # The policy is one live audition: everything else here is disposable.
        for stale in self.directory.iterdir():
            if stale.is_file():
                stale.unlink(missing_ok=True)

        entries: list[dict] = []
        for candidate in candidates:
            name = f"{token}-{candidate.index}.wav"
            (self.directory / name).write_bytes(candidate.audio)
            entries.append(
                {
                    "index": candidate.index,
                    "file": name,
                    "sample_rate": candidate.sample_rate,
                    "recipe": dict(candidate.recipe),
                }
            )

        sidecar = {
            "token": token,
            "brief": {
                "description": brief.description,
                "language": brief.language,
                "seed": brief.seed,
                "preview_text": brief.preview_text,
                "emotional": bool(emotional),
            },
            "candidates": entries,
        }
        (self.directory / f"{token}.json").write_text(
            json.dumps(sidecar, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return Audition(
            token=token,
            brief=brief,
            emotional=bool(emotional),
            candidates=candidates,
        )

    # ── read ────────────────────────────────────────────────────────────
    def load(self, token: str) -> Audition:
        """Read an audition back by token. The token is the only input."""
        if not TOKEN_RE.match(token or ""):
            raise ValidationError("token must be 12 lowercase hex characters")

        sidecar = self.directory / f"{token}.json"
        if not sidecar.is_file():
            raise VoiceNotFound(f"no audition for token {token}; generate candidates again")

        try:
            data = json.loads(sidecar.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise ValidationError(f"the audition sidecar for {token} is corrupt: {exc}") from exc
        if not isinstance(data, dict) or data.get("token") != token:
            raise ValidationError(f"the audition sidecar for {token} does not match its token")

        brief_data = data.get("brief")
        entries = data.get("candidates")
        if not isinstance(brief_data, dict) or not isinstance(entries, list):
            raise ValidationError(f"the audition sidecar for {token} is corrupt: missing fields")

        try:
            brief = VoiceBrief(
                description=str(brief_data["description"]),
                language=str(brief_data.get("language") or "Spanish"),
                candidates=len(entries),
                seed=_optional_int(brief_data.get("seed")),
                preview_text=brief_data.get("preview_text"),
            )
            candidates = tuple(
                DesignCandidate(
                    index=int(entry["index"]),
                    # Rebuilt from token+index: a sidecar cannot point us at a path.
                    audio=(self.directory / f"{token}-{int(entry['index'])}.wav").read_bytes(),
                    sample_rate=int(entry["sample_rate"]),
                    recipe=dict(entry.get("recipe") or {}),
                )
                for entry in entries
            )
        except (OSError, KeyError, TypeError, ValueError) as exc:
            raise ValidationError(f"the audition for {token} is unreadable: {exc}") from exc
        if not candidates:
            raise ValidationError(f"the audition for {token} has no candidates")

        return Audition(
            token=token,
            brief=brief,
            emotional=bool(brief_data.get("emotional")),
            candidates=candidates,
        )


def _optional_int(value: object) -> int | None:
    return None if value is None else int(value)
