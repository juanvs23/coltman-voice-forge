# E2E — MCP server over real stdio

Run: 2026-11-23 · `voice-forge serve` live on `127.0.0.1:8720` · catalog with 5
voices · `mcp==2.3.0`.

## Why this run exists

Unit tests prove the client shape and the tool functions against fakes. They
cannot prove three things this run does:

1. **The protocol handshake works** with the real `MCPServer` over stdio:
   `initialize` → `notifications/initialized` → `tools/list` → `tools/call`.
2. **stdout carries nothing but protocol.** The driver speaks raw
   newline-delimited JSON-RPC and parses every stdout line; a banner, a `print`
   or a stray log line fails the run. stderr is captured separately.
3. **The render guard holds against a live server.** A `render_dialogue` call
   with `out="catalog/alex/ref.wav"` must be refused as a readable tool error,
   **and** `voice-forge verify` must still report every voice `ok` afterwards —
   the refusal happens before any job is submitted.

## How to run

```bash
uv run voice-forge serve &          # must be up on :8720
uv run python tests/e2e/mcp-stdio/handshake.py
```

The script prints the protocol version, the tool list, the voice list and the
`verify` result, and exits non-zero on any failed assertion.

## Observed output

```
protocol 2025-06-18 · server voice-forge
tools (12): clone_voice, derive_voice, design_candidates, engine_action,
            engine_status, get_previews, list_voices, preview_voice,
            queue_status, register_candidate, render_dialogue, show_voice
voices (5): alex, alex-grave, narrador-energico, narrador-terror, narradora-ming
stdout lines all JSON: yes (4)
verify after refusal: exit 0 · alex                         ok
```

The refused call returned `isError: true` with:

```
Error executing tool render_dialogue: refusing to write into the catalog:
<repo>/catalog/alex/ref.wav is inside
<repo>/catalog. The catalog is the operator's data and a voice
reference must never be overwritten. Choose a destination under
<repo>/out.
```

`verify-after-refusal.txt` shows all five voices `ok`, unchanged.

## Files

Committed: this README and `handshake.py`.

Gitignored (`evidence/`, written by the run):

| File | Content |
|---|---|
| `handshake.stdout.jsonl` | Every stdout line from the child, one JSON message per line. Every line must parse as JSON — that is the purity proof. |
| `handshake.stderr.log` | The child's stderr, captured separately. Holds the SDK's INFO line for the refused tool; no protocol data. |
| `handshake.summary.json` | Protocol version, tool names, voices, refusal text, exit code. |
| `verify-after-refusal.txt` | `voice-forge verify` output after the refused render. |
