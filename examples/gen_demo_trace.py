#!/usr/bin/env python
"""Generate a synthetic agentic trace for the shipped demo.

The public demo must not redistribute real datasets (licensing) or third-party
agent prompts. This writes a fully invented ShareGPT-format trace — fictional
`acme` repo, fake commands and file contents — that still exercises the
simulator the same way (growing cumulative prompts → prefix reuse). Deterministic
via a fixed seed so the committed demo is reproducible.

    python examples/gen_demo_trace.py > examples/demo_trace.json
    kvlens capture --traces examples/demo_trace.json --indices 0,1,2
    kvlens events  --traces examples/demo_trace.json --indices 0,1
"""

from __future__ import annotations

import json
import random
import sys

rng = random.Random(7)

NOUNS = [
    "parser",
    "router",
    "cache",
    "loader",
    "planner",
    "indexer",
    "scheduler",
    "buffer",
    "codec",
    "session",
    "worker",
    "policy",
    "matcher",
    "reducer",
    "filter",
    "encoder",
    "decoder",
    "tracer",
    "limiter",
    "registry",
]
VERBS = [
    "build",
    "resolve",
    "merge",
    "flush",
    "encode",
    "decode",
    "scan",
    "apply",
    "commit",
    "expand",
    "reduce",
    "align",
    "emit",
    "probe",
    "batch",
    "normalize",
]
DIRS = ["core", "api", "util", "store", "net"]

# session name, number of turns, lines of fake file content per turn
SESSIONS = [("widgets", 12, 180), ("indexing", 22, 300), ("scheduler", 28, 420)]


def fake_code(n_lines: int) -> str:
    out = []
    for i in range(n_lines):
        v, n, m = rng.choice(VERBS), rng.choice(NOUNS), rng.choice(NOUNS)
        if i % 11 == 0:
            out.append(f"# {v} the {n} before the {m} is ready")
        elif i % 6 == 0:
            out.append(f"def {v}_{n}(cfg, ctx, *, retries={rng.randint(1, 5)}):")
        elif i % 6 == 1:
            out.append(f"    state = {n}_state.setdefault('{m}', [])")
        else:
            out.append(
                f"    result = {v}({n}, ctx.get('{m}'), limit={rng.randint(8, 512)})"
            )
    return "\n".join(out)


def human_turn(k: int, lines: int) -> str:
    mod = f"acme/{rng.choice(DIRS)}/{rng.choice(NOUNS)}.py"
    return (
        f"Command: /bin/bash -lc \"sed -n '1,{lines}p' {mod}\"\n"
        f"Chunk ID: {k:06x}\nWall time: 0.00 seconds\nProcess exited with code 0\n\n"
        f"{fake_code(lines)}"
    )


def gpt_turn() -> str:
    return (
        f"The change looks isolated. I'll patch {rng.choice(VERBS)}_"
        f"{rng.choice(NOUNS)}() and add a regression test."
    )


def conversation(name: str, turns: int, lines: int, preamble: str) -> dict:
    # Identical preamble across sessions → shared prefix blocks the radix tree
    # can merge/reuse before each session diverges into its own task.
    task = f"fix the {rng.choice(NOUNS)} handling in acme/{rng.choice(DIRS)}"
    msgs = [
        {"from": "human", "value": preamble},
        {"from": "gpt", "value": gpt_turn()},
        {
            "from": "human",
            "value": f"Task: {task}. Investigate the relevant modules and patch it.",
        },
    ]
    for k in range(turns):
        msgs.append({"from": "gpt", "value": gpt_turn()})
        # later turns read bigger files, so context grows unevenly (realistic)
        grow = lines + (k * lines) // max(turns, 1)
        msgs.append({"from": "human", "value": human_turn(k, grow)})
    msgs.append({"from": "gpt", "value": gpt_turn()})
    return {"conversations": msgs}


def main() -> None:
    # Built once and reused verbatim, so every session starts with the same
    # tokens (a shared repo guide) and the tree shows real cross-session reuse.
    preamble = (
        "You are contributing to the fictional `acme` monorepo. Conventions:\n\n"
        + fake_code(360)
    )
    trace = [conversation(*s, preamble) for s in SESSIONS]
    json.dump(trace, sys.stdout)


if __name__ == "__main__":
    main()
