"""Radix-tree derivation engine — the Python home of the tree.js logic.

Maintains the granular KV-block tree (one node per block hash, O(1) add/remove)
and derives, at ``view_model()`` time, the fully-merged render structure the
radix-tree tab paints: run pills, divergence markers, collapsible branches,
per-frame stats and legend. Everything visual (run-merging, prune/dim,
divergence, leaf counts) is recomputed from the node map every frame, so any
transient/malformed state self-heals on the next frame.

This is the authoritative implementation of ``AGENTS.md`` §8. The browser is a
dumb painter over the view-model; it never derives the tree. The same view-model
schema flows from a static file (demo) or over SSE (live) — see §1.

Naming note: view-model *output* keys are camelCase (``rootHash``, ``showWho``,
…) because they are the JS painter's contract; Python identifiers are snake_case.
"""

from __future__ import annotations

from collections.abc import Callable

# Attention-type short tags (mirror of tree.js SHORT).
SHORT_ATTENTION_TAGS = {
    "full_attention": "FA",
    "sliding_window": "SWA",
    "mamba": "Mamba",
    "mla": "MLA",
    "chunked_local": "Local",
}
# Dense groups are authoritative for the backbone; sparse ones only tag types.
DENSE_ATTENTION_TAGS = {"FA", "MLA"}


class _Node:
    """One block hash. ``parent_hash`` is the (possibly detached) parent hash."""

    __slots__ = ("block_hash", "parent_hash", "groups", "sessions")

    def __init__(self, block_hash: str, parent_hash: str | None):
        self.block_hash = block_hash
        self.parent_hash = parent_hash
        self.groups: set[int] = set()
        self.sessions: set[int] = set()


# A per-parent listing of child hashes; a per-hash subtree size; both are
# recomputed each frame and threaded through the derivation helpers.
ChildIndex = dict[str, list[str]]
SubtreeSizes = dict[str, int]


class RadixTree:
    """Granular block tree + render-time derivation.

    Args:
        groups: ``meta.groups`` list (each has ``id`` and ``attention_type``).
        sessions: ``meta.sessions`` list (each has ``id`` and ``label``).
        content: block hash -> decoded token preview (for snippets/drawer).
        block_size: tokens per block.
    """

    def __init__(
        self,
        groups: list[dict],
        sessions: list[dict],
        content: dict[str, str],
        block_size: int,
    ):
        self.nodes: dict[str, _Node] = {}
        self.attention_tag_by_group: dict[int, str] = {
            group["id"]: SHORT_ATTENTION_TAGS.get(group["attention_type"], "?")
            for group in groups
        }
        self.sessions = sessions or []
        self.content = content or {}
        self.block_size = block_size

    # ---- event application (O(1) per block) ----
    def apply(self, event: dict, session: int) -> None:
        """Apply one serialized event (kinds ``s``/``r``/``c``) for ``session``."""
        kind = event["k"]
        if kind == "c":
            self.nodes.clear()
            return
        if kind == "s":
            attention_tag = self.attention_tag_by_group.get(event["g"])
            is_dense = attention_tag in DENSE_ATTENTION_TAGS
            parent_hash = event.get("p")
            for block_hash in event["h"]:
                node = self.nodes.get(block_hash)
                if node is None:
                    node = _Node(block_hash, parent_hash)
                    self.nodes[block_hash] = node
                # Parent authority: dense (FA/MLA) overwrite; sparse set only if
                # still null (they report inconsistent parents for a hash).
                if is_dense or node.parent_hash is None:
                    node.parent_hash = parent_hash
                node.groups.add(event["g"])
                node.sessions.add(session)
                parent_hash = block_hash
        elif kind == "r":
            group = event.get("g")
            for block_hash in event["h"]:
                node = self.nodes.get(block_hash)
                if node is not None:
                    # sessions is never cleared on eviction (§8.2).
                    if group is None:
                        node.groups.clear()
                    else:
                        node.groups.discard(group)

    def clear(self) -> None:
        self.nodes.clear()

    # ---- derived helpers (never persisted between frames) ----
    def _attention_tags_of(self, node: _Node) -> set[str]:
        return {self.attention_tag_by_group.get(group, "?") for group in node.groups}

    def _attention_type(self, node: _Node) -> str:
        # e.g. "FA", "FA+SWA" — empty when evicted (no groups).
        return "+".join(sorted(self._attention_tags_of(node)))

    @staticmethod
    def _session_key(node: _Node) -> str:
        return ",".join(str(session_id) for session_id in sorted(node.sessions))

    def _session_label(self, session_id: int) -> str:
        for session in self.sessions:
            if session["id"] == session_id:
                return session["label"]
        return f"session {session_id + 1}"

    def _merge_key(self, node: _Node) -> str:
        # Merge along a chain by (session-set, evicted) only — NOT attention type
        # (a merged run may span FA / FA+SWA / SWA).
        is_evicted = len(node.groups) == 0
        return f"{self._session_key(node)}|{is_evicted}"

    def _color_token(self, sessions: set[int]) -> str:
        if not sessions:
            return "evicted"
        if len(sessions) > 1:
            return "shared"
        return f"sess-{next(iter(sessions)) % 6}"

    def _session_text(self, sessions: set[int]) -> str:
        if not sessions:
            return "evicted"
        if len(sessions) > 1:
            return f"Reused · {len(sessions)} sessions"
        return self._session_label(next(iter(sessions)))

    def _snippet(self, block_hash: str) -> str:
        return " ".join((self.content.get(block_hash) or "").split())[:160]

    # ---- tree helpers ----
    def _child_index(self) -> ChildIndex:
        """Map each present parent hash to its child hashes (insertion order)."""
        child_index: ChildIndex = {}
        for block_hash, node in self.nodes.items():
            if node.parent_hash is not None and node.parent_hash in self.nodes:
                child_index.setdefault(node.parent_hash, []).append(block_hash)
        return child_index

    def _garbage_collect(self) -> None:
        # Evicted leaf -> prune (cascade upward); evicted with children -> keep+dim.
        changed = True
        while changed:
            changed = False
            child_index = self._child_index()
            evicted_leaves = [
                block_hash
                for block_hash, node in self.nodes.items()
                if len(node.groups) == 0 and block_hash not in child_index
            ]
            for block_hash in evicted_leaves:
                del self.nodes[block_hash]
                changed = True

    def _subtree_sizes(self, child_index: ChildIndex) -> SubtreeSizes:
        sizes: SubtreeSizes = {}
        visiting: set[str] = set()

        def subtree_size(block_hash: str) -> int:
            if block_hash in sizes:
                return sizes[block_hash]
            if block_hash in visiting:  # cycle guard (malformed parent data)
                return 0
            visiting.add(block_hash)
            node_count = 1
            for child_hash in child_index.get(block_hash, []):
                node_count += subtree_size(child_hash)
            visiting.discard(block_hash)
            sizes[block_hash] = node_count
            return node_count

        for block_hash in self.nodes:
            subtree_size(block_hash)
        return sizes

    def _leaf_count(
        self,
        child_index: ChildIndex,
        sizes: SubtreeSizes,
        block_hash: str,
        cache: dict[str, int],
        visiting: set[str],
    ) -> int:
        # Real branch tips (continuation paths), ignoring size-1 turn-boundary
        # stubs: linear chain -> 1, fork into N -> N.
        if block_hash in cache:
            return cache[block_hash]
        if block_hash in visiting:  # cycle guard
            return 0
        visiting.add(block_hash)
        real_children = [
            child_hash
            for child_hash in child_index.get(block_hash, [])
            if sizes[child_hash] > 1
        ]
        if not real_children:
            leaf_count = 1
        else:
            leaf_count = sum(
                self._leaf_count(child_index, sizes, child_hash, cache, visiting)
                for child_hash in real_children
            )
        visiting.discard(block_hash)
        cache[block_hash] = leaf_count
        return leaf_count

    # ---- draw: build the nested view-model (Reddit-style threads) ----
    def view_model(self) -> dict:
        """Return the fully-derived render structure for the current frame.

        Shape::

            {"roots": [item, ...], "stats": {...}, "legend": [{token,label}]}

        where ``item`` is one of:
          - ``{"kind":"run", ...}``     a merged pill
          - ``{"kind":"diverge","paths":n}``
          - ``{"kind":"branch", ..., "body":[item, ...]}``
        """
        self._garbage_collect()
        child_index = self._child_index()
        sizes = self._subtree_sizes(child_index)
        leaf_count_cache: dict[str, int] = {}
        leaf_count_visiting: set[str] = set()

        def leaf_count(block_hash: str) -> int:
            return self._leaf_count(
                child_index, sizes, block_hash, leaf_count_cache, leaf_count_visiting
            )

        placed: set[str] = set()
        roots: list[dict] = []
        for block_hash, node in self.nodes.items():
            is_root = node.parent_hash is None or node.parent_hash not in self.nodes
            if is_root and block_hash not in placed:
                self._build_chain(
                    block_hash, roots, placed, child_index, sizes, leaf_count, ""
                )

        return {
            "roots": roots,
            "stats": self._stats(child_index, sizes),
            "legend": self._legend(),
        }

    def _build_chain(
        self,
        start_hash: str,
        container: list[dict],
        placed: set[str],
        child_index: ChildIndex,
        sizes: SubtreeSizes,
        leaf_count: Callable[[str], int],
        context_session_key: str,
    ) -> None:
        """Walk a linear chain, merging same-key blocks and absorbing stubs; at a
        real fork, nest each branch in its own collapsible thread."""
        head_hash = start_hash
        while head_hash is not None and head_hash not in placed:
            run = [head_hash]
            placed.add(head_hash)
            run_stubs: list[str] = []
            tail_hash = head_hash
            merge_key = self._merge_key(self.nodes[head_hash])
            while True:
                unplaced_children = [
                    child_hash
                    for child_hash in child_index.get(tail_hash, [])
                    if child_hash not in placed
                ]
                stubs = [c for c in unplaced_children if sizes[c] == 1]
                real_children = [c for c in unplaced_children if sizes[c] > 1]
                extends_run = (
                    len(real_children) == 1
                    and self._merge_key(self.nodes[real_children[0]]) == merge_key
                )
                if extends_run:
                    for stub_hash in stubs:
                        run_stubs.append(stub_hash)
                        placed.add(stub_hash)
                    run.append(real_children[0])
                    placed.add(real_children[0])
                    tail_hash = real_children[0]
                    continue
                for stub_hash in stubs:
                    run_stubs.append(stub_hash)
                    placed.add(stub_hash)
                break

            container.append(
                self._pill(run, run_stubs, leaf_count(tail_hash), context_session_key)
            )

            if len(real_children) == 1:  # type change → same thread
                head_hash = real_children[0]
                continue
            if len(real_children) > 1:  # real divergence → threads
                real_children.sort(
                    key=lambda child_hash: sizes[child_hash], reverse=True
                )
                container.append({"kind": "diverge", "paths": len(real_children)})
                for child_hash in real_children:
                    branch_body: list[dict] = []
                    node = self.nodes[child_hash]
                    container.append(
                        {
                            "kind": "branch",
                            "rootHash": child_hash,
                            "who": self._session_text(node.sessions),
                            "color": self._color_token(node.sessions),
                            "blockCount": sizes[child_hash],
                            "leaves": leaf_count(child_hash),
                            "body": branch_body,
                        }
                    )
                    # inside a branch, pills inherit its session → omit the label
                    self._build_chain(
                        child_hash,
                        branch_body,
                        placed,
                        child_index,
                        sizes,
                        leaf_count,
                        self._session_key(node),
                    )
            return

    def _pill(
        self,
        run: list[str],
        stubs: list[str],
        leaves: int,
        context_session_key: str,
    ) -> dict:
        node = self.nodes[run[0]]
        is_shared = len(node.sessions) > 1
        is_evicted = len(node.groups) == 0
        # distinct attention types contained in this merged run (order-preserving)
        if is_evicted:
            attention_types: list[str] = []
        else:
            attention_types = list(
                dict.fromkeys(
                    self._attention_type(self.nodes[block_hash])
                    for block_hash in run
                    if self._attention_type(self.nodes[block_hash])
                )
            )

        def block_entry(block_hash: str) -> list[str]:
            attention_type = self._attention_type(self.nodes[block_hash]) or "evicted"
            return [block_hash, attention_type]

        return {
            "kind": "run",
            "who": self._session_text(node.sessions),
            # label is redundant inside its own thread (branch head + rail say it)
            "showWho": self._session_key(node) != context_session_key,
            "color": self._color_token(node.sessions),
            "shared": is_shared,
            "evicted": is_evicted,
            "types": attention_types,
            "count": len(run),
            "toks": len(run) * self.block_size,
            "leaves": leaves,
            "snippet": self._snippet(run[0]),
            "blocks": [block_entry(block_hash) for block_hash in run],
            "stubCount": len(stubs),
            "stubBlocks": [block_entry(block_hash) for block_hash in stubs],
        }

    def _stats(self, child_index: ChildIndex, sizes: SubtreeSizes) -> dict:
        shared_blocks = total_blocks = dimmed_blocks = divergences = 0
        for block_hash, node in self.nodes.items():
            total_blocks += 1
            if len(node.groups) == 0:
                dimmed_blocks += 1
            if len(node.sessions) > 1:
                shared_blocks += 1
            real_children = [
                child_hash
                for child_hash in child_index.get(block_hash, [])
                if sizes[child_hash] > 1
            ]
            if len(real_children) > 1:
                divergences += 1
        return {
            "sharedBlocks": shared_blocks,
            "divergences": divergences,
            "total": total_blocks,
            "dim": dimmed_blocks,
        }

    def _legend(self) -> list[dict]:
        # Reflects only sessions present so far — never the future.
        present_sessions: set[int] = set()
        any_shared = False
        for node in self.nodes.values():
            present_sessions.update(node.sessions)
            if len(node.sessions) > 1:
                any_shared = True
        items = [
            {"token": f"sess-{session['id'] % 6}", "label": session["label"]}
            for session in self.sessions
            if session["id"] in present_sessions
        ]
        if any_shared:
            items.append({"token": "shared", "label": "reused (≥2 sessions)"})
        return items


def derive_frames(artifact: dict) -> list[dict]:
    """Derive per-frame view-models from a raw events artifact.

    ``artifact`` is the ``{meta, content, frames}`` shape written by ``events``
    capture (frames carry raw ``ev`` deltas). Returns a list of
    ``{"t", "s", "vm"}`` frames with the fully-derived view-model. Applying
    frames incrementally is identical to replaying ``0..t`` from scratch, so this
    matches the client's old ``seekTo`` output frame-for-frame.
    """
    meta = artifact["meta"]
    tree = RadixTree(
        meta.get("groups", []),
        meta.get("sessions", []),
        artifact.get("content", {}),
        meta["block_size"],
    )
    derived_frames: list[dict] = []
    for frame in artifact["frames"]:
        session = frame.get("s", 0)
        for event in frame["ev"]:
            tree.apply(event, session)
        derived_frames.append({"t": frame["t"], "s": session, "vm": tree.view_model()})
    return derived_frames
