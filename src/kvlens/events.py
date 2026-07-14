"""Capture real KV-cache events from --simulate-forward → web/kv_events.json.

Enables the block pool's event stream (BlockStored / BlockRemoved /
AllBlocksCleared), tees the events the scheduler already drains each step
(non-invasive — no ZMQ, no engine-code changes), replays a few sessions, and
records per-step frames. Every event is the engine's. Feeds the radix-tree tab.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path

from .engine import build_engine, build_groups, session_turns
from .traces import CodexTraces


def add_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--model", default="allenai/Olmo-3-7B-Think")
    p.add_argument("--traces", type=Path, default=Path("codex_swebenchpro.json"))
    p.add_argument(
        "--indices", default="273,353", help="Conversation indices to replay."
    )
    p.add_argument("--out", type=Path, default=Path("web/kv_events.json"))
    # Smaller cache + max-len so the pool fills and we get real eviction events,
    # while both sessions still fit individually.
    p.add_argument("--max-model-len", type=int, default=32768)
    p.add_argument("--kv-cache-memory-bytes", type=int, default=8 * 1024**3)
    p.add_argument("--max-output-tokens", type=int, default=64)


def _hstr(h) -> str:
    return h.hex() if isinstance(h, (bytes, bytearray)) else str(h)


def run(args: argparse.Namespace) -> None:
    indices = [int(x) for x in args.indices.split(",") if x.strip()]
    traces = CodexTraces.load(args.traces)

    from vllm import SamplingParams, TokensPrompt
    from vllm.distributed.kv_events import (
        AllBlocksCleared,
        BlockRemoved,
        BlockStored,
    )

    engine, _snapshots = build_engine(
        args.model, args.max_model_len, args.kv_cache_memory_bytes
    )
    core = engine.engine_core.engine_core
    kv_cache_config = core.scheduler.kv_cache_config
    groups = build_groups(kv_cache_config)
    tokenizer = engine.get_tokenizer()

    # Enable event queuing post-init (the scheduler's publisher stays null, so no
    # ZMQ socket) and tee the events the scheduler already drains each step.
    mgr = core.scheduler.kv_cache_manager
    mgr.enable_kv_cache_events = True
    mgr.block_pool.enable_kv_cache_events = True
    pending: list = []
    _orig_take = mgr.take_events

    def take_events_teed():
        evs = _orig_take()
        if evs:
            pending.extend(evs)
        return evs

    mgr.take_events = take_events_teed

    content: dict[str, str] = {}  # hash -> first-seen token preview
    frames: list[dict] = []
    block_size = groups[0]["block_size"] if groups else 128

    def serialize(evs: list) -> list[dict]:
        out = []
        for e in evs:
            if isinstance(e, BlockStored):
                if not e.block_hashes:
                    continue  # empty store carries no structure
                hashes = [_hstr(h) for h in e.block_hashes]
                toks = e.token_ids or []
                for i, h in enumerate(hashes):
                    if h not in content:
                        chunk = toks[i * e.block_size : (i + 1) * e.block_size]
                        content[h] = tokenizer.decode(chunk) if chunk else ""
                out.append(
                    {
                        "k": "s",
                        "h": hashes,
                        "p": _hstr(e.parent_block_hash)
                        if e.parent_block_hash is not None
                        else None,
                        "g": e.group_idx,
                        "kind": e.kv_cache_spec_kind,
                        "sw": e.kv_cache_spec_sliding_window,
                    }
                )
            elif isinstance(e, BlockRemoved):
                if not e.block_hashes:
                    continue
                out.append(
                    {
                        "k": "r",
                        "h": [_hstr(h) for h in e.block_hashes],
                        "g": e.group_idx,
                    }
                )
            elif isinstance(e, AllBlocksCleared):
                out.append({"k": "c"})
        return out

    def drain_into_frame(t: int, sess: int) -> None:
        if not pending:
            return
        ev = serialize(pending)
        pending.clear()
        if ev:
            frames.append({"t": t, "s": sess, "ev": ev})

    # Interleave sessions round-robin (turn 0 of every session, then turn 1 of
    # every session, …) so they behave like parallel users hitting the server,
    # not one finishing before the next starts. Each keeps its own context.
    sess = [
        {"i": i, "turns": session_turns(traces[idx]), "run": []}
        for i, idx in enumerate(indices)
    ]
    t = 0
    for turn_i in range(max((len(s["turns"]) for s in sess), default=0)):
        for s in sess:
            if turn_i >= len(s["turns"]):
                continue
            human_text, gpt_text = s["turns"][turn_i]
            human_ids = tokenizer.encode(human_text)
            gpt_ids = tokenizer.encode(gpt_text) if gpt_text else []
            prompt_ids = s["run"] + human_ids
            if len(prompt_ids) >= args.max_model_len:
                continue
            max_out = max(1, min(len(gpt_ids) or 1, args.max_output_tokens))
            engine.add_request(
                f"s{s['i']}-t{turn_i}",
                TokensPrompt(prompt_token_ids=prompt_ids),
                SamplingParams(
                    temperature=0.0,
                    max_tokens=max_out,
                    ignore_eos=True,
                    detokenize=False,
                    extra_args={
                        "simulated_output_token_ids": [500 + j for j in range(max_out)]
                    },
                ),
            )
            while engine.has_unfinished_requests():
                engine.step()
                drain_into_frame(t, s["i"])
                t += 1
            s["run"] = prompt_ids + gpt_ids[:max_out]
    for s in sess:
        print(f"session {s['i']} (trace #{indices[s['i']]}): {len(s['turns'])} turns")

    total_events = sum(len(f["ev"]) for f in frames)
    run_data = {
        "meta": {
            "model": args.model,
            "block_size": block_size,
            "num_blocks": kv_cache_config.num_blocks,
            "groups": groups,
            "sessions": [
                {"id": i, "label": f"trace #{idx}"} for i, idx in enumerate(indices)
            ],
            "generated_at": dt.datetime.now().isoformat(timespec="seconds"),
        },
        "content": content,
        "frames": frames,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(run_data))
    print(
        f"Wrote {args.out}: {len(frames)} frames, {total_events} events, "
        f"{len(content)} unique blocks, {len(groups)} groups"
    )
