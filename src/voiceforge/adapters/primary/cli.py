"""Command line interface.

The CLI is a primary adapter: it parses arguments, calls use cases and prints.
No business rule lives here.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from ...application.audition_store import AuditionStore
from ...container import build
from ...domain.errors import ValidationError, VoiceForgeError
from ...domain.models import Emotion, EmotionAxis, VoiceBrief
from ...domain.script import load_chapters, load_dialogue



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
    print(json.dumps(dict(container.engine.down(force=args.force)), indent=2, ensure_ascii=False))
    return 0


def _cmd_queue(container, args) -> int:
    print(json.dumps(container.queue.snapshot(), indent=2, ensure_ascii=False))
    return 0


def _cmd_runtime(container, args) -> int:
    if args.action == "status":
        print(json.dumps(container.runtime.status(), indent=2, ensure_ascii=False))
    elif args.action == "plan":
        print(json.dumps(container.runtime.plan(args.backend).as_dict(), indent=2, ensure_ascii=False))
    else:
        print(json.dumps(
            container.runtime.build(args.backend, force=args.force, jobs=args.jobs),
            indent=2,
            ensure_ascii=False,
        ))
    return 0


def _cmd_status(container, args) -> int:
    print(json.dumps(dict(container.engine.status()), indent=2, ensure_ascii=False))
    return 0


def _brief_from_args(args) -> VoiceBrief:
    return VoiceBrief(
        description=args.description,
        language=args.language,
        candidates=args.candidates,
        seed=args.seed,
        preview_text=args.preview,
    )


def _queued(container, task, *, fallback: str, kind: str = "design"):
    """Run model work through the serial queue and return its result.

    The lock is announced before the job starts, so ``down`` from another
    terminal refuses while an audition or a design is running.
    """
    job = container.queue.submit(kind, task)
    finished = container.queue.wait(job.id)
    if finished.state != "done":
        raise finished.exception or VoiceForgeError(finished.error or fallback)
    return finished.result


def _recipe_hint(recipe) -> str:
    """The one field that explains a candidate or voice, or its absence."""
    recipe = dict(recipe or {})
    for key in ("instruct", "model"):
        if recipe.get(key):
            return f"{key}={recipe[key]}"
    return "no recipe"


def _cmd_design(container, args) -> int:
    brief = _brief_from_args(args)
    voice, candidates = _queued(
        container,
        lambda: container.catalog.design(
            brief,
            slug=args.slug,
            name=args.name,
            pick=args.pick,
            tags=args.tag,
            neutral=not args.emotional,
        ),
        fallback="the design job failed",
    )
    print(f"registered: {voice.slug}  ({voice.sample_rate} Hz)  {voice.ref_audio}")
    for candidate in candidates:
        marker = "  <- picked" if candidate.index == args.pick else ""
        print(f"  candidate {candidate.index}{marker}")
    return 0


def _cmd_audition(container, args) -> int:
    brief = _brief_from_args(args)
    auditions = AuditionStore(container.settings.out_dir)

    def run():
        candidates = container.catalog.audition(brief, neutral=not args.emotional)
        return auditions.save(brief, candidates, emotional=args.emotional)

    audition = _queued(container, run, fallback="the audition job failed")

    print(f"token: {audition.token}")
    for candidate in audition.candidates:
        path = (auditions.directory / f"{audition.token}-{candidate.index}.wav").resolve()
        print(
            f"  {candidate.index}  {path}  {candidate.sample_rate} Hz  "
            f"{_recipe_hint(candidate.recipe)}"
        )
    print(
        f"Register one with: voice-forge register-candidate {audition.token} "
        "--pick 0 --slug <slug>"
    )
    return 0


def _cmd_register_candidate(container, args) -> int:
    auditions = AuditionStore(container.settings.out_dir)
    audition = auditions.load(args.token)
    if not 0 <= args.pick < len(audition.candidates):
        raise ValidationError(f"pick must be within 0..{len(audition.candidates) - 1}")

    # The audited flag travels with the sidecar, so the operator does not have
    # to repeat --emotional at the second step.
    emotional = args.emotional or audition.emotional
    voice = container.catalog.register_candidate(
        audition.candidates[args.pick],
        brief=audition.brief,
        slug=args.slug,
        name=args.name,
        pick=args.pick,
        tags=args.tag,
        neutral=not emotional,
        total=len(audition.candidates),
    )
    print(f"registered: {voice.slug}  origin={voice.origin}  ref={voice.ref_audio}")
    print(f"  recipe: {_recipe_hint(voice.recipe)}")
    return 0


def _wav_rate(path: Path) -> int:
    """Read the real sample rate instead of assuming one."""
    try:
        import wave

        with wave.open(str(path), "rb") as handle:
            return int(handle.getframerate())
    except Exception:  # noqa: BLE001 - non-PCM containers fall back
        return 24_000


def _cmd_add(container, args) -> int:
    path = Path(args.audio)
    audio = path.read_bytes()
    recipe: dict = {}
    for item in args.recipe or []:
        key, _, value = item.partition("=")
        if key.strip():
            recipe[key.strip()] = value.strip()
    if args.instruct:
        recipe["instruct"] = args.instruct
    if args.seed is not None:
        recipe["seed"] = args.seed
    if args.origin == "designed":
        recipe.setdefault("created_with", "voice_design")
    voice = container.catalog.register(
        audio,
        slug=args.slug,
        name=args.name or args.slug,
        language=args.language,
        sample_rate=_wav_rate(path),
        transcript=args.transcript,
        recipe=recipe or {"source": "external"},
        tags=args.tag,
        origin=args.origin,
        neutral=not args.emotional,
    )
    print(f"registered: {voice.slug}  {voice.ref_audio}  ({voice.sample_rate} Hz)  origin={voice.origin}")
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


def _cmd_verify(container, args) -> int:
    report = container.catalog.verify()
    if not report:
        print("the catalog is empty")
        return 0
    bad = 0
    for item in report:
        if item["ok"] is None:
            status = "unverifiable (no hash recorded)"
        elif item["ok"]:
            status = "ok"
        else:
            status = "MISMATCH — the clip changed"
            bad += 1
        print(f"{item['slug']:<28} {status}")
    return 1 if bad else 0


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
            "reference_neutral": voice.reference_neutral,
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


def _cmd_preview(container, args) -> int:
    emotion = _emotion(args.emotion, args.alpha)
    job = container.queue.submit(
        "preview",
        lambda: container.preview.preview(
            args.slug, args.text, emotion=emotion, speed=args.speed
        ),
    )
    finished = container.queue.wait(job.id)
    if finished.state == "failed":
        raise VoiceForgeError(finished.error or "the preview failed")
    path, duration, slot = finished.result
    print(f"{path}  {duration:.2f}s  (slot {slot + 1}/3)")
    return 0


def _cmd_derive(container, args) -> int:
    pitch = args.pitch if args.pitch is not None else (None if args.timbre else -2.0)
    voice = _queued(
        container,
        lambda: container.derive.derive(
            args.source,
            slug=args.slug,
            name=args.name,
            pitch_semitones=pitch,
            timbre_from=args.timbre,
            tags=tuple(args.tag),
        ),
        fallback="the derive job failed",
        kind="derive",
    )
    if args.timbre:
        print(f"derived: {voice.slug}  from {voice.recipe['derived_from']}  "
              f"timbre={voice.recipe['timbre_from']}  {voice.ref_audio}")
    else:
        print(f"derived: {voice.slug}  from {voice.recipe['derived_from']}  "
              f"{pitch:+.1f} st  {voice.ref_audio}")
    return 0


def _cmd_render(container, args) -> int:
    out = Path(args.out)
    target_lufs = None if args.no_master else args.lufs
    if args.chapter:
        chapters = load_chapters(args.script)
        results = _queued(
            container,
            lambda: container.dialogue.render_chapters(
                chapters, out.parent, out.stem, target_lufs=target_lufs
            ),
            fallback="the render job failed",
            kind="render",
        )
        for index, chapter in enumerate(results, start=1):
            lufs = "  n/a" if chapter.lufs is None else f"{chapter.lufs:+.1f}"
            print(
                f"{index:02d}  {chapter.path}  {chapter.duration_s:.1f}s  "
                f"{lufs} LUFS  {chapter.lines} lines  {chapter.name}"
            )
        total = sum(chapter.duration_s for chapter in results)
        print(f"total  {len(results)} chapters  {total:.1f}s")
        return 0

    dialogue = load_dialogue(args.script)
    job = container.queue.submit(
        "render",
        lambda: container.dialogue.render(
            dialogue,
            out,
            target_lufs=target_lufs,
        ),
    )
    finished = container.queue.wait(job.id)
    if finished.state == "failed":
        raise VoiceForgeError(finished.error or "the render job failed")
    result = finished.result
    print(f"{result.path}  {result.duration_s:.1f}s  {result.lines} lines  {', '.join(result.speakers)}")
    return 0


def _cmd_serve(container, args) -> int:
    import uvicorn

    from .http import create_app

    app = create_app(container)
    print(f"voice-forge on http://{args.host}:{args.port}")
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")
    return 0


def _cmd_mcp(container, args) -> int:
    """Serve MCP over stdio. stdout is the protocol; the API must already run."""
    from .mcp.server import run_stdio

    run_stdio()
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="voice-forge", description="Local voice catalog and narrator")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("up", help="start the model host (refuses a second instance)").set_defaults(func=_cmd_up)
    sub.add_parser("status", help="model host health").set_defaults(func=_cmd_status)
    sub.add_parser("queue", help="queue depth and recent jobs").set_defaults(func=_cmd_queue)

    runtime = sub.add_parser("runtime", help="detect the machine and build the model runtime into dist/")
    runtime.add_argument("action", nargs="?", default="status", choices=["status", "plan", "build"])
    runtime.add_argument("--backend", default="auto", choices=["auto", "cuda", "vulkan", "cpu"])
    runtime.add_argument("--force", action="store_true", help="rebuild even if the manifest matches")
    runtime.add_argument("--jobs", type=int, default=None)
    runtime.set_defaults(func=_cmd_runtime)

    down = sub.add_parser("down", help="stop the model host and free VRAM")
    down.add_argument("--force", action="store_true", help="stop even if a job is running")
    down.set_defaults(func=_cmd_down)

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
    design.add_argument("--preview", default=None, help="text the voice says while being designed")
    design.add_argument("--tag", action="append", default=[])
    design.add_argument("--emotional", action="store_true",
                        help="accept a non-neutral reference (default: neutral only)")
    design.set_defaults(func=_cmd_design)

    audition = sub.add_parser("audition", help="generate candidates and leave them on disk")
    audition.add_argument("description")
    audition.add_argument("--candidates", type=int, default=4)
    audition.add_argument("--language", default="Spanish")
    audition.add_argument("--seed", type=int, default=None)
    audition.add_argument("--preview", default=None, help="text the voice says while being designed")
    audition.add_argument("--emotional", action="store_true",
                          help="accept a non-neutral reference (default: neutral only)")
    audition.set_defaults(func=_cmd_audition)

    register_candidate = sub.add_parser(
        "register-candidate", help="register one candidate an audition left on disk"
    )
    register_candidate.add_argument("token")
    register_candidate.add_argument("--pick", type=int, default=0)
    register_candidate.add_argument("--slug", required=True)
    register_candidate.add_argument("--name", default=None)
    register_candidate.add_argument("--tag", action="append", default=[])
    register_candidate.add_argument("--emotional", action="store_true",
                                    help="accept a non-neutral reference (the audition's flag is kept)")
    register_candidate.set_defaults(func=_cmd_register_candidate)

    add = sub.add_parser("add", help="clone an existing clip into the catalog")
    add.add_argument("audio")
    add.add_argument("--slug", required=True)
    add.add_argument("--name", default=None)
    add.add_argument("--language", default="Spanish")
    add.add_argument("--transcript", default=None)
    add.add_argument("--instruct", default=None, help="the prompt that produced this clip")
    add.add_argument("--seed", type=int, default=None)
    add.add_argument("--recipe", action="append", default=[], metavar="KEY=VALUE")
    add.add_argument("--origin", choices=["imported", "designed"], default="imported")
    add.add_argument("--tag", action="append", default=[])
    add.add_argument("--emotional", action="store_true",
                     help="accept a non-neutral reference (default: neutral only)")
    add.set_defaults(func=_cmd_add)

    sub.add_parser("voices", help="list the catalog").set_defaults(func=_cmd_voices)
    sub.add_parser("verify", help="prove every voice is still its original clip").set_defaults(func=_cmd_verify)

    show = sub.add_parser("show", help="show one voice recipe")
    show.add_argument("slug")
    show.set_defaults(func=_cmd_show)

    remove = sub.add_parser("remove", help="delete a voice (irreversible)")
    remove.add_argument("slug")
    remove.set_defaults(func=_cmd_remove)

    preview = sub.add_parser("preview", help="audition a catalog voice, catalog untouched")
    preview.add_argument("slug")
    preview.add_argument("text")
    preview.add_argument("--emotion", nargs="*", default=[],
                         help="axis=value pairs, e.g. afraid=0.8")
    preview.add_argument("--alpha", type=float, default=0.6)
    preview.add_argument("--speed", type=float, default=1.0)
    preview.set_defaults(func=_cmd_preview)

    derive = sub.add_parser("derive", help="modify a catalog voice into a new one")
    derive.add_argument("source", help="slug of the voice to derive from")
    derive.add_argument("--slug", required=True)
    derive.add_argument("--name", default=None)
    derive.add_argument("--pitch", type=float, default=None,
                        help="semitones, -6..+6 (negative = deeper/older); default -2.0")
    derive.add_argument("--timbre", default=None,
                        help="slug of the voice whose timbre to borrow (instead of --pitch)")
    derive.add_argument("--tag", action="append", default=[])
    derive.set_defaults(func=_cmd_derive)

    render = sub.add_parser("render", help="render a dialogue script to one wav")
    render.add_argument("script")
    render.add_argument("--out", required=True)
    render.add_argument("--lufs", type=float, default=-14.0)
    render.add_argument("--no-master", action="store_true")
    render.add_argument("--chapter", action="store_true",
                        help="split on '## chapter:' markers and write one wav per chapter")
    render.set_defaults(func=_cmd_render)

    serve = sub.add_parser("serve", help="HTTP API + web UI")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8720)
    serve.set_defaults(func=_cmd_serve)

    sub.add_parser(
        "mcp", help="MCP server over stdio (tools for other agents; requires serve)"
    ).set_defaults(func=_cmd_mcp)

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
