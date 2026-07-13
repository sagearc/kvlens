"""Replay real agentic traces through --simulate-forward → web/run.json.

Each conversation is a session. For every human turn we build the *cumulative*
prompt (all prior turns + the new message), which is exactly why agentic traffic
gets huge prefix-cache hit rates: turn k's prompt is turn k-1's prompt plus a
small delta. We capture the engine's real per-request cached-prefix length
(NewRequestData.num_computed_tokens) by wrapping scheduler.schedule(), so the
"cached vs new" split and hit rate are the engine's numbers, not ours.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path

from .engine import build_engine, build_groups, session_turns
from .traces import CodexTraces

HEAD_HUMAN = 4000  # chars of the new user message we keep for display
HEAD_GPT = 2000


def add_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--model", default="allenai/Olmo-3-7B-Think")
    p.add_argument("--traces", type=Path, default=Path("codex_swebenchpro.json"))
    p.add_argument(
        "--indices", default="3,335,360", help="Conversation indices to replay."
    )
    p.add_argument("--out", type=Path, default=Path("web/run.json"))
    p.add_argument("--max-model-len", type=int, default=131072)
    p.add_argument("--kv-cache-memory-bytes", type=int, default=32 * 1024**3)
    p.add_argument(
        "--max-output-tokens",
        type=int,
        default=128,
        help="Cap simulated decode length per turn (output is tiny vs input).",
    )


def run(args: argparse.Namespace) -> None:
    indices = [int(x) for x in args.indices.split(",") if x.strip()]
    traces = CodexTraces.load(args.traces)

    from vllm import SamplingParams, TokensPrompt

    engine, snapshots = build_engine(
        args.model, args.max_model_len, args.kv_cache_memory_bytes
    )
    core = engine.engine_core.engine_core
    kv_cache_config = core.scheduler.kv_cache_config
    groups = build_groups(kv_cache_config)
    tokenizer = engine.get_tokenizer()

    # Non-invasive capture of per-request cached-prefix length.
    cached_by_req: dict[str, int] = {}
    sched = core.scheduler
    _orig_schedule = sched.schedule

    def schedule_wrapped(*a, **kw):
        out = _orig_schedule(*a, **kw)
        for nr in out.scheduled_new_reqs:
            cached_by_req[nr.req_id] = nr.num_computed_tokens
        return out

    sched.schedule = schedule_wrapped

    turns_out: list[dict] = []
    sessions_out: list[dict] = []
    cum_cached = cum_input = 0
    t = 0

    for sess_i, idx in enumerate(indices):
        pairs = session_turns(traces[idx])
        label = f"trace #{idx}"
        running_ids: list[int] = []  # growing context for this session
        session_turn_count = 0

        for human_text, gpt_text in pairs:
            human_ids = tokenizer.encode(human_text)
            gpt_ids = tokenizer.encode(gpt_text) if gpt_text else []
            prompt_ids = running_ids + human_ids
            if len(prompt_ids) >= args.max_model_len:
                break  # would exceed the run cap; stop this session

            max_out = max(1, min(len(gpt_ids) or 1, args.max_output_tokens))
            req_id = f"s{sess_i}-t{session_turn_count}"
            start = len(snapshots)
            # add_request returns the engine-assigned id (a random suffix is
            # appended); use it to read back the captured cached-prefix length.
            assigned = engine.add_request(
                req_id,
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

            cached = cached_by_req.get(assigned, 0)
            prompt_len = len(prompt_ids)
            cum_cached += cached
            cum_input += prompt_len
            turn_snaps = snapshots[start:]
            usage = round(max((s.kv_cache_usage for s in turn_snaps), default=0.0), 4)

            turns_out.append(
                {
                    "t": t,
                    "session": sess_i,
                    "turn": session_turn_count,
                    "human": {
                        "text": human_text[:HEAD_HUMAN],
                        "chars": len(human_text),
                    },
                    "gpt": {
                        "text": gpt_text[:HEAD_GPT],
                        "chars": len(gpt_text),
                        "tokens": len(gpt_ids),
                    },
                    "context_tokens": prompt_len,
                    "cached_tokens": cached,
                    "new_tokens": prompt_len - cached,
                    "turn_hit_rate": round(cached / prompt_len, 4)
                    if prompt_len
                    else 0.0,
                    "cum_hit_rate": round(cum_cached / cum_input, 4)
                    if cum_input
                    else 0.0,
                    "kv_usage": usage,
                    "blocks_used": round(usage * kv_cache_config.num_blocks),
                }
            )
            running_ids = prompt_ids + gpt_ids[:max_out]
            session_turn_count += 1
            t += 1

        sessions_out.append(
            {
                "id": sess_i,
                "label": label,
                "turns": session_turn_count,
                "final_context_tokens": len(running_ids),
            }
        )
        print(
            f"session {sess_i} ({label}): {session_turn_count} turns, "
            f"final context {len(running_ids):,} tokens"
        )

    run_data = {
        "meta": {
            "model": args.model,
            "block_size": groups[0]["block_size"] if groups else None,
            "num_blocks": kv_cache_config.num_blocks,
            "max_model_len": args.max_model_len,
            "hybrid": len(groups) > 1,
            "dataset": {
                "traces": len(traces),
                "median_turns": 60,
                "note": "full dataset reaches ~237K tokens; "
                f"this run capped at {args.max_model_len:,}",
            },
            "generated_at": dt.datetime.now().isoformat(timespec="seconds"),
        },
        "groups": groups,
        "sessions": sessions_out,
        "turns": turns_out,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(run_data, indent=2))
    overall = cum_cached / cum_input if cum_input else 0.0
    print(
        f"Wrote {args.out}: {len(turns_out)} turns across {len(indices)} "
        f"sessions; overall cache hit rate {overall:.1%}"
    )
