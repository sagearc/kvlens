# Contributing

The design system and the rules that keep this lean live in
[AGENTS.md](AGENTS.md) — read it first.

## Setup

```bash
make setup && uv run pre-commit install
make serve            # view the sample — no vLLM needed
```

Only regenerating data (`make capture` / `make events`) needs vLLM.

## Before a PR

- `make lint test` passes.
- Look at the result in light **and** dark mode — the palette validator checks
  color, not layout.
- Keep the diff small and follow AGENTS.md.
- Never commit data captured from a real dataset — see [SECURITY.md](SECURITY.md).
