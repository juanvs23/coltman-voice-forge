"""MCP tools: each one returns what the API returned, and propagates errors."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from voiceforge.adapters.primary.mcp import tools
from voiceforge.adapters.primary.mcp.client import ApiError
from voiceforge.adapters.primary.mcp.server import build_server


@pytest.fixture
def project_dirs(monkeypatch):
    """Pin the MCP process roots to this tree, whatever the cwd is."""
    out = Path.cwd() / "out"
    catalog = Path.cwd() / "catalog"
    monkeypatch.setattr(tools, "_project_dirs", lambda: (out, catalog))
    return out, catalog


class Broken:
    """Any attribute call raises, exactly as a down API would."""

    def __getattr__(self, _name):
        def boom(*_args, **_kwargs):
            raise ApiError(503, "engine is down", "run `voice-forge up`")

        return boom


_UNSET = object()


class FakeClient:
    """Records the call and returns a canned payload per method."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple, dict]] = []

    def _record(self, method, *args, **kwargs):
        self.calls.append((method, args, kwargs))
        return {"ok": method, "args": list(args), "kwargs": kwargs}

    def list_voices(self):
        return [{"slug": "alex"}, {"slug": "narrador-terror"}]

    def show_voice(self, slug):
        return self._record("show_voice", slug)

    def preview_voice(self, slug, text, *, axes=None, intensity=0.6, speed=1.0, hint=None):
        return self._record(
            "preview_voice",
            slug,
            text,
            axes=axes,
            intensity=intensity,
            speed=speed,
            hint=hint,
        )

    def render_dialogue(self, script, out=None, master=True):
        return self._record("render_dialogue", script, out=out, master=master)

    def design_candidates(
        self,
        description,
        candidates=4,
        language="Spanish",
        seed=None,
        preview_text=None,
        emotional=False,
    ):
        return self._record(
            "design_candidates",
            description,
            candidates=candidates,
            language=language,
            seed=seed,
            preview_text=preview_text,
            emotional=emotional,
        )

    def register_candidate(self, token, pick, slug, name=None, tags=None, emotional=False):
        return self._record(
            "register_candidate",
            token,
            pick,
            slug,
            name=name,
            tags=tags,
            emotional=emotional,
        )

    def clone_voice(
        self, audio_path, slug, name=None, language="Spanish", transcript=None, emotional=False
    ):
        return self._record(
            "clone_voice",
            audio_path,
            slug,
            name=name,
            language=language,
            transcript=transcript,
            emotional=emotional,
        )

    def derive_voice(
        self, slug, new_slug, name=None, pitch=_UNSET, timbre=None, tags=None
    ):
        kwargs = {"name": name, "timbre": timbre, "tags": tags}
        if pitch is not _UNSET:
            kwargs["pitch"] = pitch
        return self._record("derive_voice", slug, new_slug, **kwargs)

    def previews(self):
        return [{"slot": 0, "ready": False}]

    def engine_status(self):
        return {"status": "up", "backend": "cuda"}

    def engine_action(self, action):
        return self._record("engine_action", action)

    def queue_status(self):
        return {"busy": False, "pending": 0}


def test_list_voices_returns_the_catalog_as_the_api_sent_it():
    fake = FakeClient()
    assert tools.list_voices(fake) == [{"slug": "alex"}, {"slug": "narrador-terror"}]


def test_preview_voice_forwards_every_axis_and_optional_field():
    fake = FakeClient()

    result = tools.preview_voice(
        fake, "alex", "hola", axes={"sad": 0.5}, intensity=0.4, speed=0.8, hint="lento"
    )

    name, args, kwargs = fake.calls[0]
    assert name == "preview_voice"
    assert args == ("alex", "hola")
    assert kwargs == {
        "axes": {"sad": 0.5},
        "intensity": 0.4,
        "speed": 0.8,
        "hint": "lento",
    }
    assert result["ok"] == "preview_voice"


def test_preview_voice_defaults_are_the_contract_defaults():
    fake = FakeClient()
    tools.preview_voice(fake, "alex", "hola")

    _, _, kwargs = fake.calls[0]
    assert kwargs["axes"] is None
    assert kwargs["intensity"] == 0.6
    assert kwargs["speed"] == 1.0


def test_render_dialogue_passes_the_yaml_and_an_absolute_output(project_dirs):
    fake = FakeClient()
    tools.render_dialogue(fake, "lines: []", out="out/agente.wav", master=False)

    _, args, kwargs = fake.calls[0]
    assert args == ("lines: []",)
    assert kwargs == {"out": str(project_dirs[0] / "agente.wav"), "master": False}


def test_render_dialogue_without_out_lets_the_server_choose():
    fake = FakeClient()
    tools.render_dialogue(fake, "lines: []")

    assert fake.calls[0][2] == {"out": None, "master": True}


def test_render_dialogue_refuses_a_catalog_path_and_never_reaches_the_api(project_dirs):
    fake = FakeClient()

    with pytest.raises(ValueError, match="catalog"):
        tools.render_dialogue(fake, "lines: []", out="catalog/alex/ref.wav")

    assert fake.calls == []


def test_render_dialogue_refuses_a_path_that_escapes_the_output_directory(project_dirs):
    fake = FakeClient()

    with pytest.raises(ValueError, match="outside the output directory"):
        tools.render_dialogue(fake, "lines: []", out="../x.wav")

    assert fake.calls == []


def test_a_symlink_into_the_catalog_cannot_smuggle_a_destination(tmp_path):
    catalog = tmp_path / "catalog"
    (catalog / "alex").mkdir(parents=True)
    reference = catalog / "alex" / "ref.wav"
    reference.write_bytes(b"the voice")
    out = tmp_path / "out"
    out.mkdir()
    sneaky = out / "sneaky.wav"
    sneaky.symlink_to(reference)

    with pytest.raises(ValueError, match="catalog"):
        tools.resolve_render_out(str(sneaky), out_dir=out, catalog_dir=catalog)


def test_design_then_register_is_the_two_step_flow():
    fake = FakeClient()

    tools.design_candidates(fake, "voz ronca", candidates=2, seed=3)
    tools.register_candidate(fake, "tok", 1, "ronca", tags=["grave"])

    assert fake.calls[0][0] == "design_candidates"
    assert fake.calls[0][2]["candidates"] == 2
    assert fake.calls[0][2]["seed"] == 3
    assert fake.calls[1] == (
        "register_candidate",
        ("tok", 1, "ronca"),
        {"name": None, "tags": ["grave"], "emotional": False},
    )


def test_clone_and_derive_pass_the_file_path_and_pitch(tmp_path):
    clip = tmp_path / "clip.wav"
    clip.write_bytes(b"RIFFfake")
    fake = FakeClient()

    tools.clone_voice(fake, str(clip), "clon", transcript="hola")
    tools.derive_voice(fake, "alex", "alex-grave", pitch=-4.0)

    assert fake.calls[0][1] == (str(clip.resolve()), "clon")
    assert fake.calls[0][2]["transcript"] == "hola"
    assert fake.calls[1][1] == ("alex", "alex-grave")
    assert fake.calls[1][2]["pitch"] == -4.0


def test_a_timbre_derive_sends_the_timbre_and_omits_the_pitch():
    fake = FakeClient()

    tools.derive_voice(fake, "alex", "alex-hibrido", timbre="narrador-terror")

    name, args, kwargs = fake.calls[0]
    assert name == "derive_voice"
    assert args == ("alex", "alex-hibrido")
    assert kwargs["timbre"] == "narrador-terror"
    assert "pitch" not in kwargs


def test_clone_voice_refuses_a_missing_file_before_calling_the_api(tmp_path):
    fake = FakeClient()
    missing = tmp_path / "nope.wav"

    with pytest.raises(ValueError, match="audio file not found"):
        tools.clone_voice(fake, str(missing), "clon")

    assert fake.calls == []


def test_clone_voice_refuses_a_directory(tmp_path):
    fake = FakeClient()

    with pytest.raises(ValueError, match="not a regular file"):
        tools.clone_voice(fake, str(tmp_path), "clon")

    assert fake.calls == []


def test_diagnostics_delegate():
    fake = FakeClient()
    assert tools.get_previews(fake) == [{"slot": 0, "ready": False}]
    assert tools.engine_status(fake) == {"status": "up", "backend": "cuda"}
    assert tools.queue_status(fake) == {"busy": False, "pending": 0}


def test_engine_action_rejects_a_name_the_api_would_not_accept():
    fake = FakeClient()
    with pytest.raises(ValueError, match="unknown engine action"):
        tools.engine_action(fake, "restart")
    assert fake.calls == []


@pytest.mark.parametrize("action", ["up", "warm", "down"])
def test_engine_action_accepts_the_three_lifecycle_actions(action):
    fake = FakeClient()
    assert tools.engine_action(fake, action)["ok"] == "engine_action"


@pytest.mark.parametrize(
    "call",
    [
        lambda c: tools.list_voices(c),
        lambda c: tools.show_voice(c, "alex"),
        lambda c: tools.preview_voice(c, "alex", "hola"),
        lambda c: tools.render_dialogue(c, "lines: []"),
        lambda c: tools.design_candidates(c, "voz"),
        lambda c: tools.register_candidate(c, "t", 0, "s"),
        lambda c: tools.derive_voice(c, "alex", "alex-2"),
        lambda c: tools.get_previews(c),
        lambda c: tools.engine_status(c),
        lambda c: tools.engine_action(c, "up"),
        lambda c: tools.queue_status(c),
    ],
)
def test_every_tool_propagates_the_api_error(call):
    with pytest.raises(ApiError):
        call(Broken())


def test_clone_voice_propagates_the_api_error(tmp_path):
    clip = tmp_path / "clip.wav"
    clip.write_bytes(b"RIFFfake")

    with pytest.raises(ApiError):
        tools.clone_voice(Broken(), str(clip), "clon")


def test_the_registered_server_exposes_twelve_tools_and_no_delete():
    class NeverCalled:
        pass

    server = build_server(NeverCalled())

    listed = asyncio.run(server.list_tools())
    names = sorted(tool.name for tool in listed)

    assert names == [
        "clone_voice",
        "derive_voice",
        "design_candidates",
        "engine_action",
        "engine_status",
        "get_previews",
        "list_voices",
        "preview_voice",
        "queue_status",
        "register_candidate",
        "render_dialogue",
        "show_voice",
    ]
    assert not any("remove" in name or "delete" in name for name in names)


def test_no_tool_can_delete_a_voice_by_name_or_description():
    """The posture is enforced, not just stated in a docstring."""
    listed = asyncio.run(build_server(object()).list_tools())

    for tool in listed:
        haystack = f"{tool.name} {tool.description}".lower()
        assert "remove" not in haystack, tool.name
        assert "delete" not in haystack, tool.name


def test_the_docstrings_carry_the_two_safety_guards():
    listed = {tool.name: tool.description for tool in asyncio.run(build_server(object()).list_tools())}

    render = " ".join(listed["render_dialogue"].split()).lower()
    assert "catalog" in render
    assert "inside the output directory" in render

    engine = " ".join(listed["engine_action"].split()).lower()
    assert "interrupts every agent" in engine
    assert "refused while any job is running" in engine

    clone = " ".join(listed["clone_voice"].split()).lower()
    assert "regular file" in clone
    assert "cannot choose where files are written" in clone


def test_every_tool_docstring_tells_an_agent_what_it_does():
    server = build_server(object())
    for tool in asyncio.run(server.list_tools()):
        assert tool.description, f"{tool.name} has no description"
        assert len(tool.description) > 80, f"{tool.name} description is too thin"
