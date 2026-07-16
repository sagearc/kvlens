# Contributing / Agent Guide — KV-Cache Simulator viz

Guidelines for humans and AI agents working on this visualization. The
[`README.md`](README.md) is the user-facing "what it is / how to run"; **this
file is the authoritative style and design system.** If a change breaks a rule
here, it's the wrong change — or the rule needs an explicit, reasoned edit.

North star: **elegant, clean, honest, and light.** A chart is read by people and
executed by a browser. Prefer clarity over cleverness, restraint over density,
and real data over anything invented.

---

## 1. Architecture

Two decoupled halves, connected only by a **view-model** (the same JSON shape
whether it arrives from a static file or an SSE stream):

```
capture + derivation (Python)  ──►  view-model  ──►  web app = thin painter
  drives the real vLLM engine        the only          builds DOM, no derivation
  AND derives the render model       contract          (vanilla ES modules)
                                    file │ SSE
```

- **Capture + derivation** (`src/kvlens/`: `capture.py`, `events.py`,
  `engine.py`, `traces.py`, and `tree.py` — the radix-tree engine, exposed via
  the `kvlens` CLI) runs vLLM in `--simulate-forward` and derives the render
  view-model in Python. Needs the vLLM simulate-forward build (`[capture]`
  extra). **All tree logic lives in `tree.py`** (run-merging, prune/dim,
  divergence, leaf counts) — see §8 — so it is unit-testable and shared by every
  delivery path.
- **Web** (`web/`) is a no-build static app that `fetch`es the view-model (or
  receives it over SSE) and **only paints** it — it derives nothing. No bundler,
  no framework, no npm install. It ships with a sample artifact so it runs with
  zero Python and no vLLM.
- **Delivery:** the default `kvlens serve` is a zero-dependency stdlib static
  server. `kvlens serve --replay|--live` (in `server.py`, the `[serve]` extra)
  streams the *same* view-model over server-sent events — `--live` from a real
  vLLM run, consumed by `web/transport.js`'s `EventSource` mode. Live inherently
  needs a running server; the static file demo needs none.
- The view-model **is the contract.** Keep the two halves independent: the web
  app must paint any valid view-model; capture/derivation must never assume UI
  details. Client-side state is limited to collapse and the detail drawer.

There are two tabs (`index.html` = Sessions, `tree.html` = Radix tree). They are
**independent pages** sharing tokens and conventions, not a SPA. Adding a tab =
adding a page, not rewiring the others.

---

## 2. Data integrity (non-negotiable)

1. **Never fabricate a number.** Every metric shown must come from the real
   engine via capture. If the simulator can't produce it, don't show it.
2. **Capture non-invasively.** Read the engine's own signals — `SchedulerStats`,
   `kv_cache_config`, block-pool events, `NewRequestData.num_computed_tokens`.
   Wrap/tee (`scheduler.schedule`, the event queue); **do not edit PR/engine
   code** to get data out.
3. **Label limits, don't hide them.** Runs are capped (e.g. `max_model_len`);
   say so in `meta` and surface it. Redacted dataset content (lorem-ipsum
   placeholders) is shown as an explicit marker/note, never silently dropped or
   passed off as real text.
4. **Determinism.** Same trace + same args → same artifact. Seed by stable ids;
   avoid wall-clock/random in captured values.

---

## 3. Visual design system

### 3.1 Type roles

One decision drives every text style: *interesting-and-changing* vs *constant
metadata*. Pick a role; don't invent per-element sizes.

| Role | Style | Used for |
|------|-------|----------|
| **Hero** | 54px / 700, accent color | the single headline number (one per view) |
| **Value** | ~23px / 650, ink, `tabular-nums` | changing metrics (tiles, big readouts) |
| **Eyebrow** | 11px / 600, UPPERCASE, `.06em`, muted | constant region labels: section titles, tile labels, `TURN n` |
| **Meta** | 12px / 400, muted, sentence case | descriptive/technical: model line, config, subtitles |
| **Body** | 13px, ink / ink-2 | actual content (commands, messages) |

- One font everywhere: `system-ui` stack. No display/serif faces.
- `tabular-nums` on anything numeric that updates or aligns in columns.
- Titles say *what am I looking at*; put technical metadata beside them, muted.

### 3.2 Color

Colors are **CSS custom properties** in `style.css` (light + dark blocks); JS
never holds hex — it references `var(--…)` via `palette.js`.

- **Color carries meaning only.** Everything else is grayscale ink/muted → the
  result reads calm, not busy. Current semantic colors: `--cached` (green =
  reused), `--new` (orange = real prefill cost), `--sN` (session identity),
  accent green (hero).
- **Color follows the entity, never its rank.** A session keeps its hue
  regardless of position; a filter that changes counts must not repaint others.
- **Categorical hues in fixed order, never cycled.** Session palette is a
  validated trio (blue/aqua/yellow). A new series takes the next slot, never a
  generated hue.
- **Validate, don't eyeball.** Run any categorical palette through the dataviz
  validator (CVD ΔE ≥ 12 target; contrast ≥ 3:1 or provide a text label as
  relief) in **both** light and dark before shipping.
- **Dark mode is a selected variant**, not an auto-flip — its own steps against
  the dark surface, validated separately.

### 3.3 Layout

- **Centered, max-width container** (~1160px), not full-bleed. Page scrolls
  normally; don't lock the viewport.
- **No hardcoded positions.** Flex/grid with auto-flow, `minmax`, and wrap. No
  pixel `top/left`, no fixed grid indices, no per-element coordinates. Charts use
  a normalized `viewBox`, not pixel math.
- **Responsive by construction:** cards wrap; panes stack on narrow screens via a
  single breakpoint, not JS.
- **Separation by weight / size / whitespace**, not borders and pills. Reach for
  a hairline or shadow only when grouping genuinely needs it.

### 3.4 Motion

Subtle and purposeful. Entrance animations ≤ ~0.3s; transitions on values that
change. Motion should *explain* (a new item arriving, a bar growing), never
decorate. Nothing should flash on first paint — highlight only real changes.

### 3.5 Chat / avatar conventions

- Newest item **on top** so the latest is always visible without scroll-chasing.
- Identity lives in the **avatar** (face + session color + id badge). Don't
  repeat the id in the row title — the avatar carries it.
- Avatars are **per session, not per message**: seed a deterministic face by
  session id (DiceBear via `<img>`), so only a handful load and each is cached.
  Keep them light; degrade to the tinted circle + badge if the image fails.
- Soft, tinted circles + muted rings — identity color should be legible, not
  loud.

### 3.6 Granularity for the human eye

Show what a person can scan. Aggregate when raw counts exceed that: per-turn
cached/new split and a growth line, **not** 80,000 painted tokens. Long text
truncates with an expand affordance (Claude/Codex style). Merge/collapse at
render time, not in the data.

---

## 4. Code style

- **No build step.** Vanilla ES modules, one `<script type="module">`. No
  bundler, transpiler, framework, or npm dependency. Python uses the repo venv.
- **Small pure pieces.** `render(state) → DOM`; one playback clock; helpers do
  one thing. Keep files small and skimmable.
- **Data-driven, not layout-driven.** The UI renders whatever the artifact
  contains — adding a metric is a field + one tile, never new layout math.
  Deriving from a spec array (e.g. `TILES`) beats hand-placing elements.
- **Degrade, don't crash.** Missing optional fields hide their element rather
  than throwing. `null`/absent is normal.
- **Reuse before invent.** Metrics from engine structs; colors from the shared
  palette; the trace loader is plain pydantic. Don't reimplement engine logic to
  annotate data — read what the engine already reports.
- **Comments are brief and explain *why*.** The code says what; comments justify
  a non-obvious choice (a wrap, a fallback, a cap).
- **Match the surrounding style** (naming, spacing, comment density). Python is
  Google-style docstrings, 88-col; JS mirrors the existing terse module style.

---

## 5. Extending it (worked patterns)

- **Add a metric tile:** add an entry to the `TILES` spec (label + value fn +
  note fn). No layout change.
- **Add a session/trace:** pass another index to the capture; the UI adapts
  (legend, sparkline, colors) from `sessions`/`turns`. If sessions exceed the
  palette, fold extras or extend the validated palette — never cycle hues.
- **Add an attention type / group kind:** add a `--attn-<type>` token and let the
  data classify; don't branch layout on it.
- **Add a view/tab:** new page under `web/`, reusing `style.css` tokens and these
  rules. Keep existing tabs untouched.

---

## 6. Running & verifying

```bash
make setup          # uv venv + dev deps
make serve          # view the shipped sample at http://localhost:8000
make test lint      # before pushing
# regenerate data (needs the vLLM simulate-forward build):
make capture        # → web/run.json
make events         # → web/kv_events.json
```

Before opening a PR:

- **Look at it.** Open (or screenshot) the result in light *and* dark; check for
  label collisions, overflow, and geometry. The palette validator checks color,
  not layout. To exercise the live path, `kvlens serve --replay` then open
  `tree.html?live=1`.
- If you touched the tree engine, run `make test` — `tests/test_tree.py` pins the
  §8 invariants and edge cases. Verify the view-model still matches §8 and that
  the painter degrades cleanly if a field is missing.
- Keep the diff small and the reasoning defensible end-to-end (a human must
  understand and defend every line — pure agent PRs are not acceptable).

---

## 7. Scope & taste

This is a focused illustration, not a platform. **Do not over-engineer.** Resist
config knobs, abstractions, and dependencies that don't earn their keep. When in
doubt: fewer elements, more whitespace, honest numbers, one accent color.

---

## 8. Radix-tree logic (tab 2) — rules, invariants, edge cases

This is the authoritative spec for the radix-tree engine, which lives in
**`src/kvlens/tree.py`** (Python). `web/tree.js` is a thin painter that only
builds DOM from the view-model this engine emits — it derives nothing. It exists
so an agent can change the tree without re-deriving these rules. If you change
behavior, update this section **and** `tests/test_tree.py` in the same commit.

**View-model (the contract `tree.py` → painter).** `view_model()` returns
`{roots, stats, legend}` per frame; the SSE/file wrapper adds `{t, s, vm}` (live
frames also carry a `contentDelta` hash→text map). `roots` (and each branch
`body`) is an ordered list of items:

- `{kind:"run", who, showWho, color, shared, evicted, types[], count, toks,
  leaves, snippet, stubCount, blocks:[[hash,type],…], stubBlocks:[[hash,type],…]}`
  — a merged pill. `color` is a **semantic token** (`shared`/`evicted`/`sess-N`),
  never a hex value; the painter maps it to `var(--token)` (§3.2).
- `{kind:"diverge", paths}` — the fork marker.
- `{kind:"branch", rootHash, who, color, blockCount, leaves, body:[…]}` — a
  collapsible thread. **Collapse is pure client UI** (a `Set` of `rootHash`),
  never in the view-model; the painter always receives the full `body` and just
  hides collapsed ones.

`stats = {sharedBlocks, divergences, total, dim}`; `legend = [{token, label}]`.
The rules below define how these are derived; conservation (§8.11) —
`Σ(run.count) + Σ(run.stubCount) == stats.total` — is asserted every frame in
`tests/test_tree.py` over the `kv_events_edge.json` fixture and the real sample.

### 8.1 Data model (granular; everything else is derived at render)
- One node per **block hash**, in a `Map<hash, node>`. `node = { h, parentH,
  groups:Set<group_idx>, sessions:Set<session_id> }`. Add/remove is O(1).
- A node's **attention types** = `{ groupType[g] for g in node.groups }` (mapped
  from `meta.groups`, e.g. `full_attention→FA`, `sliding_window→SWA`).
- **Never** precompute merged/collapsed nodes. Merge, split, prune, dim,
  divergence, leaf counts are all recomputed from the map on every `draw()`.
  This is why any transient/malformed state self-heals on the next frame.

### 8.2 Event application (`applyEvent`)
- `BlockStored(hashes, parent, group, kind)`: for each hash in the chain, create
  the node if new; `groups.add(group)`; `sessions.add(currentFrameSession)`; set
  `parentH`. **Parent authority:** full-attention/MLA are *dense* and
  authoritative → they overwrite `parentH`. Sliding-window/Mamba are *sparse*
  (they report inconsistent parents for the same hashes) → they set `parentH`
  only if still null. FA is therefore the tree backbone; SWA contributes type
  tags, not structure.
- `BlockRemoved(hashes, group)`: `groups.delete(group)` (or clear if group is
  null). **`sessions` is never cleared** on eviction.
- `AllBlocksCleared`: clear the map.

### 8.3 Structure
- `children` are computed at render from `parentH` (each node has exactly one
  parent → it is a tree, not a DAG).
- **Root** = `parentH == null` OR parent not in the map (a *gap* → detached
  root). Multiple roots render as separate top-level chains.

### 8.4 Prune / dim (render-time GC, before layout)
- **Evicted** node ≙ `groups.size === 0`.
- Evicted **leaf** (no live children) → **prune**, and cascade to the parent.
- Evicted **internal** (has live children) → **keep, dim** (dashed, low opacity).

### 8.5 Merge (run-length) — mergeKey = `(session-set, evicted)`, NOT type
- Along a single-child chain, merge blocks with the same mergeKey into one pill.
  Attention type deliberately does **not** break a run: a merged pill may span
  FA / FA+SWA / SWA and shows the distinct types it contains as badges; the
  click drawer lists each block with its own type.
- **Turn-boundary stubs**: a size-1 leaf child hanging off a mid-chain node is a
  per-turn dead-end. The run *passes through* it (absorbing it into a
  "↳ N turn-boundary blocks" note) and keeps going. Only a **real fork** breaks
  the run.
- Split is emergent: it happens exactly where session-set or eviction changes.

### 8.6 Divergence
- A node with **≥2 real children** (subtree size > 1) is a divergence → render a
  marker + one nested collapsible branch per child.
- Turn-boundary stubs (size-1) are **not** divergences.
- **Un-fork:** if eviction removes a divergence's branch so only one real child
  remains, it is no longer a fork → it becomes a linear continuation and merges
  back into the parent thread. (Divergence count drops accordingly.)

### 8.7 Leaves / fan-out
- `leafCount` = number of **real branch tips** (continuation paths), *ignoring*
  turn-boundary stubs. Linear chain → 1. Fork into N → N. The reused root's leaf
  count equals the number of session paths below it.
- Do **not** count raw graph leaves — turn-boundary stubs would inflate it (this
  was a bug: a linear branch reported "14 leaves").

### 8.8 Reused (cross-session)
- "Reused · N sessions" ≙ `node.sessions.size === N ≥ 2` — a prefix segment held
  in cache and shared by N sessions. Colored green wherever it occurs (root, or
  *between* divergences when sessions share nested prefixes).
- **Capture caveat:** a block is tagged with a session only when that session
  *stores/re-stores* it. A 100% cache hit that never re-stores won't re-tag, so
  cross-session reuse can under-count depending on cache pressure. Prefer trace
  data where sessions share a prefix **and** diverge each turn.

### 8.9 Collapse (pure UI state)
- Reddit-thread style: each branch is a collapsible thread (caret + connector
  rail). Collapse state is a `Set` of branch-root hashes, kept out of the data
  model; it survives re-render, scrub, and live growth (keyed by hash).

### 8.10 Capture: interleave, don't serialize
- Sessions are replayed **round-robin** (turn 0 of every session, then turn 1 of
  every session, …), each keeping its own growing context — so they behave like
  parallel users hitting the server, and all reach the shared prefix together.
  Never run one session to completion before the next.

### 8.11 Invariants (assert these when changing the tree)
- **Conservation:** every live/dimmed node is rendered exactly once — as a member
  of one run pill *or* as a counted turn-boundary stub. `Σ(pill ×counts) +
  Σ(stub counts) == total nodes`. No block is ever lost or duplicated across
  merge / split / prune / gap / re-add / un-fork.
- **Self-healing:** re-derive from the map each frame; do not carry derived state
  between frames (except collapse UI state).
- **Cycle-safe:** size/leaf recursion has a visiting guard (malformed parent data
  must not infinite-loop).

### 8.12 Edge cases (must all hold; see `web/kv_events_edge.json` fixture)
1. Gap (child arrives before parent) → detached root; reconnects when parent arrives.
2. Evict leaf → prune + cascade upward.
3. Evict internal (has live child) → dim, not prune.
4. Re-add after evict → merges back live.
5. Divergence branch fully evicted → un-fork to a single chain.
6. Same hash in multiple groups (FA+SWA) → one node carrying both types.
7. Multiple sliding-window groups share hashes → one node, groups {…}.
8. Turn-boundary stub → absorbed into a note; never a leaf or a divergence.
9. Full cache hit with no re-store → reused may under-count (§8.8 caveat).
