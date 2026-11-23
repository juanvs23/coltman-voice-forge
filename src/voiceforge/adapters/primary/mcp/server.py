"""MCP server: the catalog, narration and design as agent-callable tools.

This is a **primary adapter**, not a second engine. Every tool is a client call
to the running ``voice-forge serve`` API, so model work still enters that
process's single ``SerialQueue``: agents queue FIFO behind each other, and the
admission lock remains the only truth about what is running.

Consequence, stated for the agent: **``voice-forge serve`` must be running**.
When it is not, every tool fails with ``ApiUnavailable`` and a message naming
the command that starts it.

**No ``remove_voice`` tool, on purpose.** An autonomous agent must not delete
the operator's catalog: deleting a voice destroys the reference clip, which is
the irreplaceable asset. Removal stays available to a human through the CLI
(``voice-forge remove``) and the operator console.

Transport is stdio: stdout carries the MCP protocol and nothing else. Logs and
errors go to stderr.
"""

from __future__ import annotations

import functools
import logging
import sys
from collections.abc import Callable
from typing import Any, Literal

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from . import tools
from .client import ApiError, ApiUnavailable, VoiceForgeClient

INSTRUCTIONS = """\
voice-forge is a local voice catalog and narrator. Use these tools to list the
operator's voices, audition one with emotional direction, render a YAML dialogue
script to a mastered wav, and create new voices by design or by cloning a clip.

Prerequisites: the `voice-forge serve` API must already be running on the same
machine (default http://127.0.0.1:8720). If it is not, tools fail with a message
saying so; ask the operator to start it.

Only one model job runs at a time. A synth, render or design call may block for
a long time (a render can take up to an hour) while it waits in the queue or
runs; that is expected, not a hang. Do not retry a slow call in parallel.

Deleting voices is intentionally not exposed: ask the operator to run
`voice-forge remove <slug>`.
"""


def _readable(fn: Callable[..., Any]) -> Callable[..., Any]:
    """Turn an anticipated failure into text the agent can read and act on.

    The SDK reports any exception that is not a ``ToolError`` as a bare
    "Error executing tool …" and keeps the detail in the server log. Our
    refusals and API errors carry the useful sentence, so they are re-raised as
    ``ToolError`` — the model sees *why* the call failed.
    """

    @functools.wraps(fn)
    def guarded(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except (ApiError, ApiUnavailable, ValueError, OSError) as exc:
            raise ToolError(str(exc)) from exc

    return guarded


def _package_version() -> str:
    """The installed distribution version, or "unknown" from a source checkout."""
    try:
        from importlib.metadata import version

        return version("voice-forge")
    except Exception:  # noqa: BLE001 - metadata is cosmetic, never fatal
        return "unknown"


def build_server(client: VoiceForgeClient | None = None) -> MCPServer:
    """Register every tool on a fresh ``MCPServer`` over one API client."""
    api = client or VoiceForgeClient()
    server = MCPServer(
        version=_package_version(),
        name="voice-forge",
        instructions=INSTRUCTIONS,
    )

    @server.tool()
    @_readable
    def list_voices() -> dict:
        """List every voice in the operator's catalog.

        Returns `count` and `voices`, one entry per voice with `slug`, `name`,
        `origin` (`designed`, `derived` or `imported`), `language`,
        `sample_rate`, `tags` and the `recipe` that produced it. Call this first:
        the `slug` is the identifier every other voice tool expects.
        """
        voices = tools.list_voices(api)
        return {"count": len(voices), "voices": voices}

    @server.tool()
    @_readable
    def show_voice(slug: str) -> dict:
        """Show one catalog voice in full, including its provenance.

        Returns the same fields as `list_voices` plus `ref_audio` (the reference
        clip on disk) and the complete `recipe` (brief, language, seed, model,
        `derived_from` when applicable). Raises an error when the slug is not in
        the catalog.
        """
        return tools.show_voice(api, slug)

    @server.tool()
    @_readable
    def preview_voice(
        slug: str,
        text: str,
        axes: dict[str, float] | None = None,
        intensity: float = 0.6,
        speed: float = 1.0,
        hint: str | None = None,
    ) -> dict:
        """Synthesize one line with a catalog voice, leaving the catalog untouched.

        Use it to audition delivery before a long render. `axes` maps emotion
        names to 0..1 weights; valid names are `happy`, `angry`, `sad`,
        `afraid`, `disgusted`, `melancholic`, `surprised`, `calm`. `intensity`
        (0..1) scales the whole mix, `speed` is a multiplier around 1.0, and
        `hint` is extra free-text direction in the language of the voice.
        Returns `path`, `url`, `slot` (one of three rotating preview files) and
        `duration_s`. Blocks through the serial queue; allow up to ~15 minutes.
        """
        return tools.preview_voice(
            api,
            slug,
            text,
            axes=axes,
            intensity=intensity,
            speed=speed,
            hint=hint,
        )

    @server.tool()
    @_readable
    def render_dialogue(script: str, out: str | None = None, master: bool = True) -> dict:
        """Render a YAML dialogue script to one continuous, mastered wav.

        `script` is the full YAML text, not a path: a root mapping with a
        `lines:` list, where each line names `voice` (a catalog slug), `text`,
        and optionally `emotion` (axis weights plus `intensity`), `speed` and
        `pause_after_ms`. `out` is the destination path; omit it to write
        `out/render.wav` in the operator's workspace. A given path must resolve
        **inside the output directory** and never inside `catalog/`: a render
        cannot overwrite a voice reference, so a path like
        `catalog/<slug>/ref.wav` is rejected before any job starts.
        `master=True` normalizes loudness to -14 LUFS; pass False for raw
        segments. Returns `job`, `path`, `duration_s`, `lines` and `speakers`.
        This is the longest call available: it can block for up to an hour, so
        use it once the script is final and the voices are already chosen with
        `preview_voice`.
        """
        return tools.render_dialogue(api, script, out=out, master=master)

    @server.tool()
    @_readable
    def design_candidates(
        description: str,
        candidates: int = 4,
        language: str = "Spanish",
        seed: int | None = None,
        preview_text: str | None = None,
        emotional: bool = False,
    ) -> dict:
        """Generate candidate voices from a text description, without registering one.

        This is the first half of creating a voice: nothing enters the catalog
        here. `description` is the brief in plain language (age, timbre, pace,
        character). `candidates` is how many takes to generate (typically 2-4).
        `language` is the spoken language; `seed` makes one run reproducible.
        `preview_text` is the sentence the candidates say. Returns a `token` and
        the candidate list; pass the token to `register_candidate` to keep one.
        Blocks through the serial queue; allow up to ~30 minutes.
        """
        return tools.design_candidates(
            api,
            description,
            candidates=candidates,
            language=language,
            seed=seed,
            preview_text=preview_text,
            emotional=emotional,
        )

    @server.tool()
    @_readable
    def register_candidate(
        token: str,
        pick: int,
        slug: str,
        name: str | None = None,
        tags: list[str] | None = None,
        emotional: bool = False,
    ) -> dict:
        """Register one candidate from an earlier `design_candidates` call.

        `token` comes from `design_candidates`; `pick` is the candidate index to
        keep. `slug` is the immutable identifier for the new voice (lowercase,
        digits and hyphens) and `name` is the display name. `tags` are free
        labels. A registered voice cannot be changed later; create another slug
        instead. Returns the new `voice` plus `candidates` and `picked`. Fails if
        the slug is already taken or the pick is out of range.
        """
        return tools.register_candidate(
            api,
            token,
            pick,
            slug,
            name=name,
            tags=tags,
            emotional=emotional,
        )

    @server.tool()
    @_readable
    def clone_voice(
        audio_path: str,
        slug: str,
        name: str | None = None,
        language: str = "Spanish",
        transcript: str | None = None,
        emotional: bool = False,
    ) -> dict:
        """Register an existing audio file as a catalog voice (zero-shot clone).

        `audio_path` is a local path readable by the MCP process on the machine
        running `voice-forge serve`: a short, clean recording of the target
        voice. It must exist and be a regular file. `slug` is the immutable
        identifier and `name` the display name. `transcript` is the text spoken
        in the clip, when known. There is no destination parameter on purpose:
        the voice always lands in `catalog/<slug>/`, and the API validates the
        slug, so the agent cannot choose where files are written. Returns
        `slug`, `name` and `origin`.
        """
        return tools.clone_voice(
            api,
            audio_path,
            slug,
            name=name,
            language=language,
            transcript=transcript,
            emotional=emotional,
        )

    @server.tool()
    @_readable
    def derive_voice(
        slug: str,
        new_slug: str,
        name: str | None = None,
        pitch: float = -2.0,
        timbre: str | None = None,
        tags: list[str] | None = None,
    ) -> dict:
        """Create a new voice from an existing one, by pitch or by timbre.

        `slug` is the source voice; it is never modified. `new_slug` is the new
        immutable identifier. Two mutually exclusive transforms exist. `pitch`
        is in semitones, roughly -6..+6, where negative is deeper/older; use it
        for a younger or older sibling of a voice you already have. `timbre` is
        the slug of a second catalog voice whose timbre to borrow while keeping
        `slug`'s performance and timing — one call does not accept both, and
        when `timbre` is set the pitch is not sent. Returns `slug`, `origin`,
        `derived_from`, `pitch_semitones` and `timbre_from`.
        """
        return tools.derive_voice(
            api,
            slug,
            new_slug,
            name=name,
            pitch=pitch,
            timbre=timbre,
            tags=tags,
        )

    @server.tool()
    @_readable
    def get_previews() -> dict:
        """Read the three rotating preview slots.

        Returns `slots`: each slot reports whether it holds audio, its `url` and
        the metadata of the take that produced it (voice, text, emotion,
        duration). Use it to find a preview made earlier in the session. Empty
        slots are included, in order, so position is stable.
        """
        slots = tools.get_previews(api)
        return {"slots": slots}

    @server.tool()
    @_readable
    def engine_status() -> dict:
        """Report the model host: `status`, `url` and `backend`.

        `status` is `up` when the host answers and `down` otherwise. A down host
        does not stop the API, but synth, render and design calls will fail
        until it is started.
        """
        return tools.engine_status(api)

    @server.tool()
    @_readable
    def engine_action(action: Literal["up", "warm", "down"]) -> dict:
        """Control the model host process.

        `action` is one of: `up` (start it; fails if one is already running),
        `warm` (load weights and run a canary synthesis, so the first real line
        is not the slow one) or `down` (stop it and free VRAM). `down` interrupts
        every agent sharing this host, not just you, and is refused while any job
        is running; never call it to "fix" a slow render. Use `engine_status`
        first and prefer `warm` over `down`+`up`.
        """
        return tools.engine_action(api, action)

    @server.tool()
    @_readable
    def queue_status() -> dict:
        """Report the single serial job queue.

        Returns `busy`, the `active` job, `pending`/`queued` counts and the last
        jobs with their state. Call it when a previous call seems stuck: if a
        job is `running`, the work is in progress, not lost. There is exactly
        one worker, so your call may be waiting behind someone else's.
        """
        return tools.queue_status(api)

    return server


def run_stdio() -> None:
    """Serve the MCP protocol over stdio. Nothing else may touch stdout."""
    # httpx logs one INFO line per request. stderr is legal, but a host that
    # surfaces stderr as an error does not need our request log.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    server = build_server()
    server.run(transport="stdio")


def main() -> int:
    try:
        run_stdio()
    except KeyboardInterrupt:
        return 130
    except Exception as exc:  # noqa: BLE001 - a crash must be visible, not silent
        print(f"voice-forge mcp: {exc}", file=sys.stderr)
        return 1
    return 0
