# kvlens

**A lens on the KV cache.** kvlens makes KV-cache behavior *visible*: it replays
real agentic LLM traces through vLLM's `--simulate-forward` mode — the real
scheduler and KV-cache manager, but a *virtual* cache (no weights, no attention
kernels, runs on CPU) — and shows what the engine actually does, turn by turn.

> 🔗 **Live demo:** https://sagearc.github.io/kvlens/

Agentic traces re-send the whole conversation each turn, so a turn's prompt is
the previous one plus a small delta. kvlens lets you *see* how the cache and
scheduler handle that:

- per-turn **cached vs newly-prefilled** tokens
- **context length** as it grows across turns
- **KV-cache usage**, block counts, and prefix-cache activity
- **KV-cache groups** and their attention types (full / sliding-window — HMA)
- block **store / evict** events as a live radix tree
- each trace as a session in a live stream

Every number is captured from the engine — nothing is fabricated or embellished.

### Why the vLLM-native simulator

kvlens builds on the native KV-cache simulator
([vllm-project/vllm#47922](https://github.com/vllm-project/vllm/pull/47922))
rather than an external model. Running through vLLM's real scheduler and
KV-cache manager means the model-derived cache config — KV-cache groups,
per-layer attention types, hybrid full/sliding attention, eviction — comes
straight from the engine and stays aligned as vLLM evolves, instead of being
re-implemented and drifting out of date. kvlens just reads and draws it.

## Quick start — just view it

The viewer is a static, no-build web app and ships with a **scrubbed synthetic
sample** (`web/*.sample.json`) — real numbers and structure, placeholder text —
so you need nothing but a browser:

```bash
git clone https://github.com/sagearc/kvlens
cd kvlens
python -m http.server 8000 --directory web   # or: pipx run kvlens serve
# open http://localhost:8000
```

Two tabs: **Sessions** (`index.html`) and **Radix tree** (`tree.html`).

## Regenerate the data (optional, needs the vLLM simulator)

Only needed to produce your own `run.json` / `kv_events.json`. Capture depends on
the **native KV-cache simulator** (`--simulate-forward`), added in
[vllm-project/vllm#47922](https://github.com/vllm-project/vllm/pull/47922). Until
it lands upstream, the `capture` extra installs it from the branch (plain
`pip install vllm` does not include it yet):

```bash
make setup                                    # uv venv + dev tools
VLLM_USE_PRECOMPILED=1 uv pip install -e '.[capture]'   # + the simulator build
kvlens capture --traces path/to/traces.json --indices 3,335,360
kvlens events  --traces path/to/traces.json --indices 273,353
kvlens serve
```

Real captures (`web/run.json`, `web/kv_events.json`) embed licensed dataset and
agent content, so they are git-ignored. Run `kvlens scrub <in> <out>` to produce
a shareable `*.sample.json` before committing.

`VLLM_USE_PRECOMPILED=1` skips the long native compile — the simulator path is
Python-level and runs on CPU.

Traces are **ShareGPT format** (`[{"conversations": [{"from", "value"}]}]`). The
loader is `kvlens.traces`. The SWE-bench Pro / Codex dataset used in the demo has
its own license and is **not** bundled — bring your own trace file.

## Layout

```
src/kvlens/    capture tool: traces loader, engine glue, capture/events, CLI
web/           the static viewer (HTML/CSS/vanilla ES modules) + sample data
examples/      a tiny sample trace
tests/         light unit tests for the loader
```

The `run.json` / `kv_events.json` schema and the design system are documented in
[`AGENTS.md`](AGENTS.md).

## Credits & license

- Licensed under **Apache-2.0** (see [`LICENSE`](LICENSE)).
- Built on [vLLM](https://github.com/vllm-project/vllm) (Apache-2.0).
- Avatars via [DiceBear](https://dicebear.com) (loaded at runtime; individual
  styles carry their own licenses).
- The demo dataset (SWE-bench Pro / Codex traces) is not redistributed here.

AI assistance was used in building this project.
