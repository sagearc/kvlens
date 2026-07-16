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
from collections.abc import Callable
from pathlib import Path

from .engine import build_engine, build_groups, session_turns
from .traces import CodexTraces


def add_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--model", default="allenai/Olmo-3-7B-Think")
    parser.add_argument("--traces", type=Path, default=Path("codex_swebenchpro.json"))
    parser.add_argument(
        "--indices", default="273,353", help="Conversation indices to replay."
    )
    parser.add_argument("--out", type=Path, default=Path("web/kv_events.json"))
    # Smaller cache + max-len so the pool fills and we get real eviction events,
    # while both sessions still fit individually.
    parser.add_argument("--max-model-len", type=int, default=32768)
    parser.add_argument("--kv-cache-memory-bytes", type=int, default=8 * 1024**3)
    parser.add_argument("--max-output-tokens", type=int, default=64)


def _hash_to_str(block_hash) -> str:
    if isinstance(block_hash, (bytes, bytearray)):
        return block_hash.hex()
    return str(block_hash)


def _capture(args: argparse.Namespace):
    """Build the simulate-forward engine and return ``(meta, content, frames)``.

    ``frames`` is a generator yielding raw per-step frames (``{"t","s","ev"}``)
    as the engine runs; ``content`` is the shared hash->text map it populates
    along the way (safe to read after each yielded frame). Both ``run`` (file)
    and ``run_live`` (SSE) consume this one path, so the capture logic — and the
    tree.py derivation applied to it — lives in exactly one place.
    """
    conversation_indices = [int(x) for x in args.indices.split(",") if x.strip()]
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
    engine_core = engine.engine_core.engine_core
    kv_cache_config = engine_core.scheduler.kv_cache_config
    groups = build_groups(kv_cache_config)
    tokenizer = engine.get_tokenizer()

    # Enable event queuing post-init (the scheduler's publisher stays null, so no
    # ZMQ socket) and tee the events the scheduler already drains each step.
    cache_manager = engine_core.scheduler.kv_cache_manager
    cache_manager.enable_kv_cache_events = True
    cache_manager.block_pool.enable_kv_cache_events = True
    pending_events: list = []
    take_events_original = cache_manager.take_events

    def take_events_teed():
        events = take_events_original()
        if events:
            pending_events.extend(events)
        return events

    cache_manager.take_events = take_events_teed

    content: dict[str, str] = {}  # block hash -> first-seen token preview
    block_size = groups[0]["block_size"] if groups else 128

    def serialize(engine_events: list) -> list[dict]:
        serialized: list[dict] = []
        for event in engine_events:
            if isinstance(event, BlockStored):
                if not event.block_hashes:
                    continue  # empty store carries no structure
                block_hashes = [_hash_to_str(value) for value in event.block_hashes]
                token_ids = event.token_ids or []
                for block_index, block_hash in enumerate(block_hashes):
                    if block_hash not in content:
                        start = block_index * event.block_size
                        chunk = token_ids[start : start + event.block_size]
                        content[block_hash] = tokenizer.decode(chunk) if chunk else ""
                serialized.append(
                    {
                        "k": "s",
                        "h": block_hashes,
                        "p": _hash_to_str(event.parent_block_hash)
                        if event.parent_block_hash is not None
                        else None,
                        "g": event.group_idx,
                        "kind": event.kv_cache_spec_kind,
                        "sw": event.kv_cache_spec_sliding_window,
                    }
                )
            elif isinstance(event, BlockRemoved):
                if not event.block_hashes:
                    continue
                serialized.append(
                    {
                        "k": "r",
                        "h": [_hash_to_str(value) for value in event.block_hashes],
                        "g": event.group_idx,
                    }
                )
            elif isinstance(event, AllBlocksCleared):
                serialized.append({"k": "c"})
        return serialized

    meta = {
        "model": args.model,
        "block_size": block_size,
        "num_blocks": kv_cache_config.num_blocks,
        "groups": groups,
        "sessions": [
            {"id": session_id, "label": f"trace #{conversation_index}"}
            for session_id, conversation_index in enumerate(conversation_indices)
        ],
        "generated_at": dt.datetime.now().isoformat(timespec="seconds"),
    }

    def frames():
        # Interleave sessions round-robin (turn 0 of every session, then turn 1
        # of every session, …) so they behave like parallel users hitting the
        # server, not one finishing before the next. Each keeps its own context.
        session_states = [
            {
                "id": session_id,
                "turns": session_turns(traces[conversation_index]),
                "prior_token_ids": [],
            }
            for session_id, conversation_index in enumerate(conversation_indices)
        ]
        frame_index = 0
        turn_count = max((len(state["turns"]) for state in session_states), default=0)
        for turn_index in range(turn_count):
            for session_state in session_states:
                if turn_index >= len(session_state["turns"]):
                    continue
                human_text, gpt_text = session_state["turns"][turn_index]
                human_token_ids = tokenizer.encode(human_text)
                gpt_token_ids = tokenizer.encode(gpt_text) if gpt_text else []
                prompt_token_ids = session_state["prior_token_ids"] + human_token_ids
                if len(prompt_token_ids) >= args.max_model_len:
                    continue
                output_token_count = max(
                    1, min(len(gpt_token_ids) or 1, args.max_output_tokens)
                )
                engine.add_request(
                    f"s{session_state['id']}-t{turn_index}",
                    TokensPrompt(prompt_token_ids=prompt_token_ids),
                    SamplingParams(
                        temperature=0.0,
                        max_tokens=output_token_count,
                        ignore_eos=True,
                        detokenize=False,
                        extra_args={
                            "simulated_output_token_ids": [
                                500 + offset for offset in range(output_token_count)
                            ]
                        },
                    ),
                )
                while engine.has_unfinished_requests():
                    engine.step()
                    if pending_events:
                        events = serialize(pending_events)
                        pending_events.clear()
                        if events:
                            yield {
                                "t": frame_index,
                                "s": session_state["id"],
                                "ev": events,
                            }
                    frame_index += 1
                session_state["prior_token_ids"] = (
                    prompt_token_ids + gpt_token_ids[:output_token_count]
                )
        for session_state in session_states:
            conversation_index = conversation_indices[session_state["id"]]
            turn_total = len(session_state["turns"])
            print(
                f"session {session_state['id']} "
                f"(trace #{conversation_index}): {turn_total} turns"
            )

    return meta, content, frames()


def run(args: argparse.Namespace) -> None:
    """Capture a full run and write the pre-derived view-model artifact."""
    meta, content, frame_iterator = _capture(args)
    raw_frames = list(frame_iterator)
    total_events = sum(len(frame["ev"]) for frame in raw_frames)
    # Derive the render view-model in Python so the browser only paints (see
    # tree.py / AGENTS.md §1, §8). The derived frames compress well (repetitive
    # structure), so shipping whole frames stays smaller-than-raw once gzipped.
    from .tree import derive_frames

    artifact = {
        "meta": meta,
        "content": content,
        "frames": derive_frames(
            {"meta": meta, "content": content, "frames": raw_frames}
        ),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(artifact, separators=(",", ":")))
    print(
        f"Wrote {args.out}: {len(raw_frames)} frames, {total_events} events, "
        f"{len(content)} unique blocks, {len(meta['groups'])} groups"
    )


def _store_hashes(events: list[dict]) -> list[str]:
    """Block hashes newly stored by this frame's events (for content deltas)."""
    hashes: list[str] = []
    for event in events:
        if event["k"] == "s":
            hashes.extend(event["h"])
    return hashes


def run_live(args: argparse.Namespace, emit: Callable[[dict], None]) -> None:
    """Drive the engine and ``emit`` SSE messages for a live radix-tree stream.

    ``emit(message)`` receives dict messages: one ``{"type":"meta", ...}`` first,
    then ``{"type":"frame", "t", "s", "vm", "contentDelta"}`` per step. Reuses
    ``_capture`` and the shared tree.py derivation, so the live and file paths
    never diverge — the browser renders live frames with the same painter it uses
    for the committed demo.
    """
    from .tree import RadixTree

    meta, content, frame_iterator = _capture(args)
    radix_tree = RadixTree(
        meta["groups"], meta["sessions"], content, meta["block_size"]
    )
    emit({"type": "meta", "meta": meta})
    for raw_frame in frame_iterator:
        for event in raw_frame["ev"]:
            radix_tree.apply(event, raw_frame["s"])
        content_delta = {
            block_hash: content[block_hash]
            for block_hash in _store_hashes(raw_frame["ev"])
            if block_hash in content
        }
        emit(
            {
                "type": "frame",
                "t": raw_frame["t"],
                "s": raw_frame["s"],
                "vm": radix_tree.view_model(),
                "contentDelta": content_delta,
            }
        )
