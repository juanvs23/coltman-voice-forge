"""Command line interface.

The CLI is a primary adapter: it parses arguments, calls use cases and prints.
No business rule lives here.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from ...container import build
from ...domain.errors import VoiceForgeError
from ...domain.models import Emotion, EmotionAxis, VoiceBrief
from ...domain.script import load_dialogue


def _emotion(raw: list[str], intensity: float) -> Emotion:
    axes: dict[EmotionAxis, float] = {}
    for item in raw:
        if "=" not in item:
            raise VoiceForgeError(f"--emotion expects axis=value, got {item!r}")
        axis, value = item.split("=", 1)
        axes[EmotionAxis(axis.strip())] = float(value)
    return Emotion(axes=axes, intensity=intensity)


def _cmd_up(container, args) -> int:
    print(json.dumps(dict(container.engine.up()), indent=2, ensure_ascii=False))
    return 0


def _cmd_warm(container, args) -> int:
    print(json.dumps(dict(container.engine.warm(args.modes)), indent=2, ensure_ascii=False))
    return 0


def _cmd_down(container, args) -> int:
    print(json.dumps(dict(container.engine.down()), indent=2, ensure_ascii=False))
    return 0


def _cmd_status(container, args) -> int:
    print(json.dumps(dict(container.engine.status()), indent=2, ensure_ascii=False))
    return 0


def _cmd_design(container, args) -> int:
    brief = VoiceBrief(
        description=args.description,
        language=args.language,
        candidates=args.candidates,
        seed=args.seed,
    )
    voice, candidates = container.catalog.design(
        brief, slug=args.slug, name=args.name, pick=args.pick, tags=args.tag
    )
    print(f"registered: {voice.slug}  ({voice.sample_rate} Hz)  {voice.ref_audio}")
    for candidate in candidates:
        marker = "  <- picked" if candidate.index == args.pick else ""
        print(f"  candidate {candidate.index}{marker}")
    return 0


def _cmd_add(container, args) -> int:
    audio = Path(args.audio).read_bytes()
    voice = container.catalog.register(
        audio,
        slug=args.slug,
        name=args.name or args.slug,
        language=args.language,
        transcript=args.transcript,
        tags=args.tag,
    )
    print(f"registered: {voice.slug}  {voice.ref_audio}")
    return 0


def _cmd_voices(container, args) -> int:
    voices = container.catalog.list()
    if not voices:
        print("the catalog is empty — create one with `voice-forge design ...`")
        return 0
    for voice in voices:
        tags = f"  [{', '.join(voice.tags)}]" if voice.tags else ""
        print(f"{voice.slug:<28} {voice.origin:<9} {voice.language:<10}{tags}")
    return 0


def _cmd_show(container, args) -> int:
    voice = container.catalog.get(args.slug)
    print(json.dumps(
        {
            "slug": voice.slug,
            "name": voice.name,
            "origin": voice.origin,
            "language": voice.language,
            "sample_rate": voice.sample_rate,
            "ref_audio": str(voice.ref_audio),
            "transcript": bool(voice.ref_transcript),
            "recipe": dict(voice.recipe),
        },
        indent=2,
        ensure_ascii=False,
    ))
    return 0


def _cmd_remove(container, args) -> int:
    container.catalog.remove(args.slug)
    print(f"removed: {args.slug}")
    return 0


def _cmd_render(container, args) -> int:
    dialogue = load_dialogue(args.script)
    result = container.dialogue.render(
        dialogue,
        Path(args.out),
        target_lufs=None if args.no_master else args.lufs,
    )
    print(f"{result.path}  {result.duration_s:.1f}s  {result.lines} lines  {', '.join(result.speakers)}")
    return 0


def _cmd_serve(container, args) -> int:
    import uvicorn

    from .http import create_app

    app = create_app(container)
    print(f"voice-forge on http://{args.host}:{args.port}")
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="voice-forge", description="Local voice catalog and narrator")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("up", help="start the model host").set_defaults(func=_cmd_up)
    sub.add_parser("down", help="stop the model host and free VRAM").set_defaults(func=_cmd_down)
    sub.add_parser("status", help="model host health").set_defaults(func=_cmd_status)

    warm = sub.add_parser("warm", help="load weights and run a canary synthesis")
    warm.add_argument("--modes", nargs="*", default=None, choices=["design", "speech"])
    warm.set_defaults(func=_cmd_warm)

    design = sub.add_parser("design", help="create a voice from a text description")
    design.add_argument("description")
    design.add_argument("--slug", required=True)
    design.add_argument("--name", default=None)
    design.add_argument("--language", default="Spanish")
    design.add_argument("--candidates", type=int, default=4)
    design.add_argument("--pick", type=int, default=0)
    design.add_argument("--seed", type=int, default=None)
    design.add_argument("--tag", action="append", default=[])
    design.set_defaults(func=_cmd_design)

    add = sub.add_parser("add", help="clone an existing clip into the catalog")
    add.add_argument("audio")
    add.add_argument("--slug", required=True)
    add.add_argument("--name", default=None)
    add.add_argument("--language", default="Spanish")
    add.add_argument("--transcript", default=None)
    add.add_argument("--tag", action="append", default=[])
    add.set_defaults(func=_cmd_add)

    sub.add_parser("voices", help="list the catalog").set_defaults(func=_cmd_voices)

    show = sub.add_parser("show", help="show one voice recipe")
    show.add_argument("slug")
    show.set_defaults(func=_cmd_show)

    remove = sub.add_parser("remove", help="delete a voice (irreversible)")
    remove.add_argument("slug")
    remove.set_defaults(func=_cmd_remove)

    render = sub.add_parser("render", help="render a dialogue script to one wav")
    render.add_argument("script")
    render.add_argument("--out", required=True)
    render.add_argument("--lufs", type=float, default=-14.0)
    render.add_argument("--no-master", action="store_true")
    render.set_defaults(func=_cmd_render)

    serve = sub.add_parser("serve", help="HTTP API + web UI")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8720)
    serve.set_defaults(func=_cmd_serve)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    container = build()
    try:
        return int(args.func(container, args) or 0)
    except VoiceForgeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
