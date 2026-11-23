# MCP server — the catalog as agent tools

`voice-forge mcp` exposes the catalog, narration and voice creation as
**Model Context Protocol tools** over stdio, so an agent in another project
(Claude Desktop, OpenCode, any MCP host) can list voices, audition them, render
a script and create new voices without shelling out to the CLI.

## It is a client of the API, not a second engine

The MCP server is another **primary adapter**. Every tool is an HTTP call to
`voice-forge serve`, so model work still enters that process's single
`SerialQueue`:

- two agents, or an agent and the operator console, queue **FIFO** behind each
  other instead of competing for the GPU;
- the admission lock (`out/active-job.lock`) stays the one truth about what is
  running, `down` still refuses while a job runs, and there is never a second
  scheduler.

The consequence is a hard prerequisite: **`voice-forge serve` must be running.**
When it is not, every tool fails with:

```
voice-forge serve is not running on http://127.0.0.1:8720; start it with `voice-forge serve`
```

Start it first, in its own terminal:

```bash
uv run voice-forge serve        # API + console on :8720
```

The API URL defaults to `http://127.0.0.1:8720` and is overridable with
`VOICEFORGE_API_URL`.

## Client configuration

Claude Desktop (`claude_desktop_config.json`) and any host that uses the
`mcpServers` shape:

```json
{
  "mcpServers": {
    "voice-forge": {
      "command": "uv",
      "args": [
        "run",
        "--directory",
        "/path/to/voice-forge",
        "voice-forge",
        "mcp"
      ]
    }
  }
}
```

OpenCode (`opencode.json`) uses the same command as an array:

```json
{
  "mcp": {
    "voice-forge": {
      "type": "local",
      "command": [
        "uv",
        "run",
        "--directory",
        "/path/to/voice-forge",
        "voice-forge",
        "mcp"
      ],
      "enabled": true
    }
  }
}
```

`uv run --directory …` makes the host work regardless of its own working
directory. If you prefer, point `command` at the `voice-forge` entry point in
the project's `.venv` directly.

## Tools

Twelve tools. Times are the client timeout per call; the call is **blocking**
for its whole duration, including time spent waiting in the queue.

| Tool | What it does | Timeout |
|---|---|---|
| `list_voices()` | Every catalog voice with `slug`, `name`, `origin`, `language`, `tags`, `recipe`. Returns `count` + `voices`. | 15 s |
| `show_voice(slug)` | One voice in full, including `ref_audio` and recipe. | 15 s |
| `preview_voice(slug, text, axes, intensity, speed, hint)` | Synthesize one line without touching the catalog. Eight axes: `happy, angry, sad, afraid, disgusted, melancholic, surprised, calm`. | 900 s |
| `render_dialogue(script, out, master)` | Render a YAML script (the YAML **text**, not a path) to one mastered wav. `out` must resolve inside the output directory and never inside `catalog/`. | 3600 s |
| `design_candidates(description, candidates, language, seed, preview_text, emotional)` | Generate candidates from a brief; nothing is registered. Returns a `token`. | 1800 s |
| `register_candidate(token, pick, slug, name, tags, emotional)` | Register one candidate from that token. | 120 s |
| `clone_voice(audio_path, slug, name, language, transcript, emotional)` | Upload a local clip and register it as a voice (multipart). | 120 s |
| `derive_voice(slug, new_slug, name, pitch, tags)` | Create a pitch-shifted sibling; the source is untouched. | 300 s |
| `get_previews()` | The three rotating preview slots and their metadata. | 15 s |
| `engine_status()` | Model host status, URL and backend. | 15 s |
| `engine_action(action)` | `up` \| `warm` \| `down`. | 15 s |
| `queue_status()` | `busy`, active job, pending count, recent jobs. | 15 s |

The two-step design flow is intentional: `design_candidates` spends GPU time and
returns a token; the operator (or agent) listens and only then registers one
candidate. `clone_voice` reads the file in the MCP process and uploads it, so the
path must exist on this machine.

## What an agent cannot do

The catalog is the operator's data. One wrong model decision must not be able to
destroy it, so three limits are enforced by the tool layer, not left to the
model's judgement:

- **Delete voices.** There is no `remove_voice` (or any remove/delete) tool. The
  reference clip is the irreplaceable asset, and a "clean up the catalog" that a
  model hallucinated would be irreversible. Removal stays with the operator:
  `voice-forge remove <slug>` or the console.
- **Write outside `out/`.** `render_dialogue(out=…)` resolves the path to an
  absolute one and refuses anything outside the output directory or inside
  `catalog/` — symlinks included, because `Path.resolve()` runs before the check.
  Omit `out` and the server picks `out/render.wav`. This is what stops a render
  from overwriting `catalog/<slug>/ref.wav`.
- **Bypass admission.** No tool starts a second engine, and `down` is refused
  while a job runs. `engine_action` warns that `down` interrupts every agent
  sharing the host, not just the caller.

`clone_voice` has no destination parameter for the same reason: the voice always
lands in `catalog/<slug>/`, and the slug is validated by the API, so an agent
cannot choose where files are written. It only reads a local audio file, and it
must exist and be a regular file.

Every refusal is returned as a readable tool error (not a bare "tool failed"),
so the agent can correct its argument instead of retrying blindly.

## Limits

- **Blocking calls, one scheduler.** A render can take up to an hour. That is
  work in progress, not a hang; retrying in parallel only adds queue entries.
  `queue_status` shows whether the job is running.
- **Local only, no auth.** The API binds `127.0.0.1` and the MCP server speaks
  stdio. There is no token, no TLS and no multi-user story; do not expose the
  API port beyond the machine.
- **Destructive work is not exposed.** See "What an agent cannot do" above.
- **Nothing on stdout but protocol.** stdout carries MCP messages; logs and
  errors go to stderr. Do not wrap the command in something that prints a
  banner.

## Verifying an installation

With `serve` running, the committed handshake script performs a real
`initialize` → `notifications/initialized` → `tools/list` → `tools/call`
`list_voices` exchange over raw stdio and asserts that every stdout line is
valid JSON:

```bash
uv run python tests/e2e/mcp-stdio/handshake.py
```

It writes stdout, stderr and a summary to the gitignored
`tests/e2e/mcp-stdio/evidence/`. See that folder's README for the expected
output.
