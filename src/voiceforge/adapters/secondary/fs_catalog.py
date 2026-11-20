"""Catalog on disk: one directory per voice.

Layout (gitignored):

    catalog/<slug>/
    ├── voice.json     the recipe: how to reproduce this voice
    ├── ref.wav        the reference clip (immutable)
    └── GUIDE.md       human guide: provenance and usage examples
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Sequence

from ...domain.errors import ValidationError, VoiceExists, VoiceNotFound
from ...domain.models import NewVoice, Voice


class FileCatalog:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    # ── writes ──────────────────────────────────────────────────────────
    def save(self, new: NewVoice, audio: bytes) -> Voice:
        target = self.root / new.slug
        if target.exists():
            raise VoiceExists(f"slug already in the catalog: {new.slug}")

        staging = self.root / f".{new.slug}.staging"
        if staging.exists():
            shutil.rmtree(staging)
        staging.mkdir(parents=True)

        (staging / "ref.wav").write_bytes(audio)
        (staging / "voice.json").write_text(
            json.dumps(self._payload(new), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        (staging / "GUIDE.md").write_text(self._guide(new), encoding="utf-8")
        staging.rename(target)
        return self.get(new.slug)

    def remove(self, slug: str) -> None:
        target = self.root / slug
        if not (target / "voice.json").exists():
            raise VoiceNotFound(f"no such voice: {slug}")
        shutil.rmtree(target)

    # ── reads ───────────────────────────────────────────────────────────
    def list(self) -> Sequence[Voice]:
        voices = []
        for entry in sorted(self.root.iterdir()):
            if entry.is_dir() and (entry / "voice.json").exists():
                voices.append(self._load(entry))
        return voices

    def get(self, slug: str) -> Voice:
        target = self.root / slug
        if not (target / "voice.json").exists():
            raise VoiceNotFound(f"no such voice: {slug}")
        return self._load(target)

    # ── internals ───────────────────────────────────────────────────────
    @staticmethod
    def _payload(new: NewVoice) -> dict:
        return {
            "slug": new.slug,
            "name": new.name,
            "language": new.language,
            "sample_rate": new.sample_rate,
            "created_at": new.created_at,
            "origin": new.origin,
            "ref_transcript": new.ref_transcript,
            "tags": list(new.tags),
            "ref_audio": "ref.wav",
            "recipe": dict(new.recipe),
        }

    @staticmethod
    def _load(directory: Path) -> Voice:
        data = json.loads((directory / "voice.json").read_text(encoding="utf-8"))
        ref = directory / data.get("ref_audio", "ref.wav")
        if not ref.exists():
            raise ValidationError(f"{directory.name}: voice.json points to a missing ref.wav")
        return Voice(
            slug=data["slug"],
            name=data["name"],
            ref_audio=ref,
            language=data.get("language", "Spanish"),
            sample_rate=int(data.get("sample_rate", 24_000)),
            recipe=data.get("recipe", {}),
            created_at=data.get("created_at", ""),
            ref_transcript=data.get("ref_transcript"),
            tags=tuple(data.get("tags", ())),
            origin=data.get("origin", "designed"),
        )

    @staticmethod
    def _guide(new: NewVoice) -> str:
        recipe = json.dumps(dict(new.recipe), ensure_ascii=False, indent=2)
        transcript = new.ref_transcript or "(no transcript — cloned in speaker-only mode)"
        return f"""# {new.name}

| Field | Value |
|---|---|
| slug | `{new.slug}` |
| origin | {new.origin} |
| language | {new.language} |
| sample rate | {new.sample_rate} Hz |
| created at | {new.created_at} |

## How to use it

```bash
voice-forge voices                       # see the whole catalog
voice-forge render guion.yaml --out out/x.wav
```

```yaml
# reference this voice by slug
lines:
  - voice: {new.slug}
    text: "..."
    emotion: {{ afraid: 0.6, calm: 0.4 }}
    speed: 0.95
```

## Recipe (reproducible)

```json
{recipe}
```

## Reference transcript

{transcript}

## Note

A voice is immutable once registered: to change it, create a new slug.
The reference clip is what every future line is cloned from — deleting it
deletes the voice.
"""
