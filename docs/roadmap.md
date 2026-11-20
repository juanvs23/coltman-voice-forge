# Roadmap

## Next step
The three verbs work end to end, and the server transport cut a two-line render
from 46 s to 25.6 s. What is left is the CPU itself: ~9.5 s per short line is
synthesis time, not startup. Next lever, in order of value:
1. **GPU backend** — `libvulkan-dev` + `glslc` (portable) or the full NVIDIA
   toolkit; rebuild with `--force`. Expected: the biggest single win.
2. Batch a whole script in one request (the server accepts one text per call;
   a batch route would remove the per-request overhead).
3. Compare speaker-only conditioning against ICL by ear: ICL is slower and
   over-generates, but fidelity was not evaluated perceptually.

### GPU backends

This box is **Nobara 44** (Fedora family, `dnf`). CUDA is installed in pieces:
`nvcc`, `cudart`, `nvrtc` and `cccl` (13.2, from `nobara-appstream`) plus
`libcublas` 13.3, but **no cuFFT** — which is exactly the library
`audio.cpp` links.

Zero-risk path (no `sudo`, nothing installed system-wide):

```bash
dnf download --destdir dist/rpms libcufft-devel libcufft
cd dist/cuda && rpm2cpio ../rpms/libcufft-*.rpm | cpio -idm
cmake -S dist/src/audio.cpp -B dist/build-cuda \
  -DENGINE_ENABLE_CUDA=ON -DCMAKE_CUDA_ARCHITECTURES=89 \
  -DCMAKE_CUDA_COMPILER=/usr/bin/nvcc \
  -DCMAKE_LIBRARY_PATH=$PWD/dist/cuda/usr/lib64 \
  -DCMAKE_INCLUDE_PATH=$PWD/dist/cuda/usr/include
```

The resulting binary needs `LD_LIBRARY_PATH=dist/cuda/usr/lib64` at runtime.

System-wide alternative, only if other tools should see cuFFT too:
`sudo dnf install libcufft-devel` (2 packages, 278 MB, nothing installed owns
`libcufft*`, no kernel or driver change).

**Do not** install `libcublas-devel-13-1-0` from `cuda-fedora42`: it collides
with the installed `libcublas-devel-13.3.0.5` and would downgrade it.

Vulkan remains a portable fallback but was never evaluated here.

## Phases

### P1 — Skeleton that runs (current)
- [x] Hexagonal layout: `domain` / `application` / `adapters`.
- [x] Ports: catalog, designer, synthesizer, assembler, engine control.
- [x] `CatalogService` with design-then-register and imported clips.
- [x] `DialogueService` with per-line emotion, speed and pauses.
- [x] Filesystem catalog with `voice.json` recipe and `GUIDE.md`.
- [x] Model host over HTTP (stdlib server, zero extra deps in the model venv).
- [x] CLI (`up/warm/down/status/design/add/voices/show/remove/render/serve`).
- [x] REST API + single-file web UI.
- [x] ffmpeg assembler with optional loudness normalisation.
- [x] Unit + integration tests with fakes (no GPU).
- [ ] First end-to-end render with the real engine (blocked on P2 decision).

### P2 — Emotion that actually lands (Apache/MIT only) — done

**Decision (2026-11-20): Ming-3.0-TTS-0.5B in GGUF, via audio.cpp.** The
operator's criterion is architectural, not cosmetic: a pinned C++ binary plus
one GGUF file has no dependency resolution, no venv, no torch — nothing that
can drift under the project. This outweighs a marginal quality difference.

**Outcome.** The adapter composes the eight axes into one short Spanish
instruction (`template_name=freeform`) and the operator confirmed the emotion
is audible. Intensity is expressed in words, not numbers; there is no `0.1 vs
0.9` dial, and that is the remaining gap against ZONOS3, not a blocker.

| Fact | Value |
|---|---|
| Model licence | **MIT** (weights keep upstream MIT) |
| Languages | zh, en, ja, ko, de, fr, **es** |
| Package | one GGUF with backbone + flow head + audio VAE + CAMPPlus speaker encoder + tokenizer |
| Sizes | bf16 3.0 GB · Q8_0 1.7 GB |
| Peak VRAM | **1,924 MiB** Q8_0 / 2,768 MiB bf16 (measured by the provider on a 5090) |
| Runtime | `audiocpp_cli` / `audiocpp_server`, backends CPU, CUDA, Vulkan, HIP, Metal, WebGPU |
| Tasks | `tts`, `clon` (with or without transcript), `vdes` (voice design) |
| Output | mono 44.1 kHz |
| Extras | speaker-embedding export/reuse, streaming, OpenAI-compatible `/v1/audio/speech` |

**Honest limitation:** Ming's emotion is either a categorical label
(`template_name=emotion`, one label) or free-text `instruct`. There is **no
numeric intensity axis**. Our eight axes map to instruction wording, exactly
like the current Qwen adapter — so this closes design + clone + emotion in one
runtime, but "fine" control stays coarse compared with ZONOS3's numeric
vectors.

Consequence for the roadmap: ship Ming first (single runtime, MIT, 1.9 GB
VRAM). Keep the `Emotion` port unchanged. If later the numeric dial proves
necessary, ZONOS3 becomes a second speech adapter — not a rewrite.

Sweep context: 2,698 TTS models seen on 2026-11-20, 942 Apache/MIT, 188 of those
Spanish or multilingual. Rejected: IndexTTS-2.5 (bilibili), VibeVoice
("research purpose use"), Libra-TTS / Kokoro / MeloTTS (no emotion control).

Acceptance: rendering the same line with `afraid:0.1` and `afraid:0.9` produces
audibly different takes, and `/health` reports the real backend.

### P3 — Delivery polish
- Batch narration (one script → chaptered files) with per-scene loudness.
- Optional SSML-ish pauses inside a line.
- Voice versioning: allow `slug@2` without breaking old scripts.

## Debt schedule
_(none yet — every marker would be listed here with its resolution steps)_
