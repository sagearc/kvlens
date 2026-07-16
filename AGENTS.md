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

Two decoupled halves, connected only by a JSON file:

```
capture (Python)  ──►  web/*.json  ──►  static web app (vanilla ES modules)
  drives the real         the only          renders + plays it back
  vLLM engine             contract
```

- **Capture** (`src/kvlens/`: `capture.py`, `events.py`, `engine.py`,
  `traces.py`, exposed via the `kvlens` CLI) runs vLLM in `--simulate-forward`
  and writes a JSON artifact. Needs the vLLM simulate-forward build (`[capture]`
  extra).
- **Web** (`web/`) is a no-build static app that `fetch`es that JSON and renders
  it. No bundler, no framework, no npm install. It ships with a sample artifact
  so it runs with zero Python and no vLLM.
- The JSON schema **is the contract.** Keep the two halves independent: the web
  app must render any valid artifact; capture must never assume UI details.

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
  not layout.
- Verify the artifact still validates against the schema in the README, and that
  the UI degrades cleanly if a field is missing.
- Keep the diff small and the reasoning defensible end-to-end (a human must
  understand and defend every line — pure agent PRs are not acceptable).

---

## 7. Scope & taste

This is a focused illustration, not a platform. **Do not over-engineer.** Resist
config knobs, abstractions, and dependencies that don't earn their keep. When in
doubt: fewer elements, more whitespace, honest numbers, one accent color.
