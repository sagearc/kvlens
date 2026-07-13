#!/usr/bin/env python
"""Block committing sample data that carries real dataset / agent content.

The public demo must ship synthetic data only (see examples/gen_demo_trace.py).
Real captures (e.g. SWE-bench Pro / Codex) carry licensed text and third-party
agent prompts, so this guards `web/*.json` against them. Wired as a pre-commit
hook; a failure means a real leak, not a nuisance.
"""

import sys

# Substrings that only appear in real captured traces, never in the synthetic
# demo. Extend if you replay a dataset with different giveaways.
MARKERS = (
    "permissions instructions",
    "sandbox_mode",
    "skills_instructions",
    "openai-docs",
    "/app/",
    "openlibrary",
)


def main(paths: list[str]) -> int:
    bad = False
    for p in paths:
        try:
            txt = open(p, encoding="utf-8", errors="ignore").read().lower()
        except OSError:
            continue
        hit = [m for m in MARKERS if m in txt]
        if hit:
            print(
                f"{p}: looks like real captured data (markers: {', '.join(hit)}). "
                "The demo ships synthetic data only — see SECURITY.md."
            )
            bad = True
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
