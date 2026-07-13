"""Replace real trace text with synthetic filler, keeping every number.

Captured artifacts embed real dataset content (commands, file paths, and the
agent's own system prompt). This produces a shippable sample: all metrics,
hashes, and structure are preserved, but human-turn text and decoded block text
are swapped for obviously-synthetic placeholders — so the viz looks identical and
nothing real is published. Assistant turns are already redacted placeholders in
the source dataset, so they are left as-is.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

_LINES = [
    'command  /bin/bash -lc "sed -n 1,200p src/app/core.py"\n'
    "exit code 0\noutput elided in synthetic sample",
    'command  /bin/bash -lc "rg -n handler src tests"\n'
    "exit code 0\noutput elided in synthetic sample",
    'command  /bin/bash -lc "pytest -q tests/test_core.py"\n'
    "exit code 0\noutput elided in synthetic sample",
    'command  /bin/bash -lc "cat src/app/settings.py"\n'
    "exit code 0\noutput elided in synthetic sample",
]


def _line(i: int) -> str:
    return _LINES[i % len(_LINES)]


def scrub_run(data: dict) -> dict:
    for i, turn in enumerate(data.get("turns", [])):
        if "human" in turn:
            turn["human"]["text"] = _line(i)  # keep .chars (a length, not content)
    return data


def scrub_events(data: dict) -> dict:
    for i, h in enumerate(data.get("content", {})):
        data["content"][h] = _line(i)
    return data


def add_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("infile", type=Path, help="captured run.json or kv_events.json")
    p.add_argument("outfile", type=Path, help="scrubbed *.sample.json to write")


def run(args: argparse.Namespace) -> None:
    data = json.loads(args.infile.read_text())
    scrub_events(data) if "content" in data else scrub_run(data)
    args.outfile.write_text(json.dumps(data))
    print(f"wrote {args.outfile}")
