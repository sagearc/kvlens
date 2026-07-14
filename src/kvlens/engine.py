"""Shared vLLM engine setup for the capture tools.

Everything vLLM-specific lives here so the capture modules stay small and the
CLI can import them without importing vLLM (heavy) — vLLM is imported lazily
inside the functions that actually need it.

Requires a vLLM build with ``--simulate-forward`` (see the README): the engine
runs the real scheduler + KV-cache manager on CPU with a *virtual* KV cache
(no weights, no attention kernels).
"""

from __future__ import annotations

import os

# Simulated forward is CPU + single-process; set before vLLM is imported.
os.environ.setdefault("VLLM_ENABLE_V1_MULTIPROCESSING", "0")
# Agentic contexts exceed the model's trained position limit; simulated forward
# never runs RoPE/attention, so overriding the max length is safe here.
os.environ.setdefault("VLLM_ALLOW_LONG_MAX_MODEL_LEN", "1")


def attention_type(spec) -> str:
    """Friendly, stable name for a KV-cache spec. Subclasses first."""
    from vllm.v1.kv_cache_interface import (
        ChunkedLocalAttentionSpec,
        FullAttentionSpec,
        MambaSpec,
        MLAAttentionSpec,
        SlidingWindowSpec,
    )

    for cls, name in (
        (MambaSpec, "mamba"),
        (MLAAttentionSpec, "mla"),
        (SlidingWindowSpec, "sliding_window"),
        (ChunkedLocalAttentionSpec, "chunked_local"),
        (FullAttentionSpec, "full_attention"),
    ):
        if isinstance(spec, cls):
            return name
    return type(spec).__name__


def build_groups(kv_cache_config) -> list[dict]:
    groups = []
    for gid, group in enumerate(kv_cache_config.kv_cache_groups):
        spec = group.kv_cache_spec
        groups.append(
            {
                "id": gid,
                "attention_type": attention_type(spec),
                "num_layers": len(group.layer_names),
                "block_size": getattr(spec, "block_size", None),
                "sliding_window": getattr(spec, "sliding_window", None),
                "page_bytes": _page_bytes(spec),
            }
        )
    return groups


def _page_bytes(spec) -> int:
    try:
        return int(spec.page_size_bytes)  # KV bytes per block, one layer
    except Exception:
        return 0


def make_capture_logger(sink: list):
    """A per-engine StatLogger that appends each step's SchedulerStats."""
    from vllm.v1.metrics.loggers import StatLoggerBase

    class CaptureLogger(StatLoggerBase):
        def __init__(self, vllm_config, engine_index: int = 0):
            self.vllm_config = vllm_config

        def record(
            self, scheduler_stats, iteration_stats, mm_cache_stats=None, engine_idx=0
        ):
            if scheduler_stats is not None:
                sink.append(scheduler_stats)

        def log_engine_initialized(self):
            pass

    return CaptureLogger


def build_engine(model: str, max_model_len: int, kv_cache_memory_bytes: int):
    """Build a simulated-forward engine. Returns (engine, snapshots) where
    snapshots is a list the capture logger appends SchedulerStats to."""
    from vllm.engine.arg_utils import EngineArgs
    from vllm.v1.engine.llm_engine import LLMEngine

    snapshots: list = []
    engine_args = EngineArgs(
        model=model,
        simulate_forward=True,
        enforce_eager=True,
        max_model_len=max_model_len,
        kv_cache_memory_bytes=kv_cache_memory_bytes,
        enable_prefix_caching=True,
        disable_hybrid_kv_cache_manager=False,
    )
    engine = LLMEngine.from_engine_args(
        engine_args, stat_loggers=[make_capture_logger(snapshots)]
    )
    return engine, snapshots


def session_turns(conv) -> list[tuple[str, str]]:
    """(human_text, gpt_reply_text) pairs; drops a trailing unpaired human."""
    msgs = conv.conversations
    pairs = []
    i = 0
    while i < len(msgs):
        if msgs[i].role.value == "human":
            reply = msgs[i + 1].value if i + 1 < len(msgs) else ""
            pairs.append((msgs[i].value, reply))
            i += 2
        else:
            i += 1
    return pairs
