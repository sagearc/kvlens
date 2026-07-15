"""Tests for the radix-tree engine (src/kvlens/tree.py).

These encode the AGENTS.md §8 spec that used to live only as prose beside the
browser JS: the §8.11 invariants and every §8.12 edge case, driven by the
committed `web/kv_events_edge.json` fixture, plus conservation over the real
captured sample. The frame indices below are deterministic (same fixture → same
frames), so they double as a regression pin on the derivation.
"""

import json
from pathlib import Path

import pytest

from kvlens.tree import RadixTree, derive_frames

WEB = Path(__file__).parent.parent / "web"
EDGE = WEB / "kv_events_edge.json"
SAMPLE = WEB / "kv_events.json"


# ---- helpers over a view-model ----
def runs(items):
    """Yield every run pill, descending into branch bodies."""
    for it in items:
        if it["kind"] == "run":
            yield it
        elif it["kind"] == "branch":
            yield from runs(it["body"])


def branches(items):
    for it in items:
        if it["kind"] == "branch":
            yield it
            yield from branches(it["body"])


def hashes(items):
    """All block hashes present (run blocks + absorbed stubs), recursively."""
    out = set()
    for r in runs(items):
        out.update(h for h, _ in r["blocks"])
        out.update(h for h, _ in r["stubBlocks"])
    return out


def root_run_with(vm, h):
    """The top-level (non-nested) run pill whose blocks include hash `h`, or None."""
    for it in vm["roots"]:
        if it["kind"] == "run" and any(bh == h for bh, _ in it["blocks"]):
            return it
    return None


def conserved(items):
    """Σ(pill counts) + Σ(stub counts) across the whole nested structure."""
    tot = 0
    for it in items:
        if it["kind"] == "run":
            tot += it["count"] + it["stubCount"]
        elif it["kind"] == "branch":
            tot += conserved(it["body"])
    return tot


@pytest.fixture
def edge_vms():
    return derive_frames(json.loads(EDGE.read_text()))


# ---- §8.11 conservation: every live/dimmed node rendered exactly once ----
def test_conservation_edge(edge_vms):
    for i, fr in enumerate(edge_vms):
        vm = fr["vm"]
        assert conserved(vm["roots"]) == vm["stats"]["total"], f"frame {i}"


def test_conservation_real_sample():
    # The shipped sample is already in view-model form; validate the committed
    # artifact itself conserves every frame (no re-derivation needed).
    data = json.loads(SAMPLE.read_text())
    frames = data["frames"]
    assert len(frames) > 0
    for i, fr in enumerate(frames):
        vm = fr["vm"]
        assert conserved(vm["roots"]) == vm["stats"]["total"], f"frame {i}"
    # cross-session reuse is the whole point — the sample must exhibit some.
    assert frames[-1]["vm"]["stats"]["sharedBlocks"] > 0


# ---- §8.12 edge cases ----
def test_case1_gap_then_reconnect(edge_vms):
    # frame 3: "g" stored with parent "f" before "f" exists → detached root.
    assert root_run_with(edge_vms[3]["vm"], "g") is not None
    # frame 4: "f" arrives → "g" reconnects below it and is no longer a root.
    assert root_run_with(edge_vms[4]["vm"], "g") is None
    assert "g" in hashes(edge_vms[4]["vm"]["roots"])


def test_case2_evict_leaf_prunes(edge_vms):
    # "d" is a live leaf through frame 4, then removed at frame 5 → pruned.
    assert "d" in hashes(edge_vms[4]["vm"]["roots"])
    assert "d" not in hashes(edge_vms[5]["vm"]["roots"])


def test_case3_evict_internal_dims(edge_vms):
    # frame 6: "c" is evicted but still has child "x" → kept and dimmed, not pruned.
    vm = edge_vms[6]["vm"]
    assert "c" in hashes(vm["roots"])
    cpill = next(r for r in runs(vm["roots"]) if r["blocks"][0][0] == "c")
    assert cpill["evicted"] is True
    assert cpill["types"] == []  # evicted → no type badges
    assert vm["stats"]["dim"] == 1


def test_case4_readd_merges_back_live(edge_vms):
    # frame 7: "c" re-stored → live again, nothing dimmed.
    vm = edge_vms[7]["vm"]
    cpill = next(r for r in runs(vm["roots"]) if r["blocks"][0][0] == "c")
    assert cpill["evicted"] is False
    assert cpill["types"] == ["FA+SWA"]
    assert vm["stats"]["dim"] == 0


def test_case5_diverge_then_unfork(edge_vms):
    # frame 4 forks (S0 vs S1); frame 5 evicts the S0 tail → un-forks to a chain.
    assert edge_vms[4]["vm"]["stats"]["divergences"] == 1
    assert list(branches(edge_vms[4]["vm"]["roots"]))
    assert edge_vms[5]["vm"]["stats"]["divergences"] == 0
    assert not list(branches(edge_vms[5]["vm"]["roots"]))


def test_case6_fa_and_swa_one_node(edge_vms):
    # frame 0: "a" is stored by both a full-attention and a sliding-window group;
    # it is a single node carrying both types.
    apill = root_run_with(edge_vms[0]["vm"], "a")
    assert "FA+SWA" in apill["types"]
    assert dict(apill["blocks"])["a"] == "FA+SWA"


def test_case8_turn_boundary_stub_absorbed(edge_vms):
    # frame 1: "d" hangs off the a-b-c chain as a size-1 stub → absorbed into a
    # note, never a leaf or a divergence.
    vm = edge_vms[1]["vm"]
    pill = root_run_with(vm, "a")
    assert pill["stubCount"] == 1
    assert dict(pill["stubBlocks"]).get("d") is not None
    assert pill["leaves"] == 1  # not inflated by the stub
    assert vm["stats"]["divergences"] == 0


def test_leafcount_counts_fork_paths(edge_vms):
    # §8.7: reused root's leaf count == number of session paths below it.
    root = root_run_with(edge_vms[4]["vm"], "a")
    assert root["leaves"] == 2


# ---- §8.11 cycle-safety: malformed parent data must not infinite-loop ----
def test_cycle_safe():
    data = {
        "meta": {
            "block_size": 4,
            "groups": [{"id": 0, "attention_type": "full_attention"}],
            "sessions": [{"id": 0, "label": "S0"}],
        },
        "content": {},
        "frames": [
            {"t": 0, "s": 0, "ev": [{"k": "s", "h": ["a"], "p": "b", "g": 0}]},
            {"t": 1, "s": 0, "ev": [{"k": "s", "h": ["b"], "p": "a", "g": 0}]},
        ],
    }
    vms = derive_frames(data)  # terminates → guards work
    assert len(vms) == 2


def test_clear_event_resets():
    t = RadixTree(
        [{"id": 0, "attention_type": "full_attention"}],
        [{"id": 0, "label": "S0"}],
        {},
        4,
    )
    t.apply({"k": "s", "h": ["a", "b"], "p": None, "g": 0}, 0)
    assert t.view_model()["stats"]["total"] == 2
    t.apply({"k": "c"}, 0)
    assert t.view_model()["stats"]["total"] == 0
