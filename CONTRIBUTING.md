# Contributing to kvlens

Thanks for your interest! kvlens is a small, focused visualization — see
[`AGENTS.md`](AGENTS.md) for the design system and the rules that keep it lean.
This file is just the mechanics.

## Setup

```bash
make setup        # uv venv + dev tools (ruff, pytest, pre-commit)
uv run pre-commit install
make serve        # view the shipped sample
```

You do **not** need vLLM to work on the viewer or the trace loader — only to
regenerate captured data (`make capture` / `make events`), which needs the vLLM
`--simulate-forward` build.

## Before you open a PR

- `make lint test` passes.
- **Look at the result** in light *and* dark mode (screenshot it) — check for
  overflow, label collisions, geometry. The palette validator checks color, not
  layout.
- Keep the diff small and follow the guidelines in `AGENTS.md` (data-driven, no
  hardcoded layout, color = meaning only, never fabricate numbers, no build
  step). If a change needs to break a rule there, say why.
- Don't commit large data files (the dataset is git-ignored). Add a small sample
  under `examples/` if you need fixtures.

## Reporting issues

Include what you did, what you expected, and what you saw (a screenshot helps for
UI issues). For data issues, mention the trace source and the `kvlens capture`
command you ran.
