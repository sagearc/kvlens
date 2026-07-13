// Radix-tree tab — a human-readable, Reddit-thread-style view of the KV cache:
// which blocks are REUSED across sessions (shared prefix), where sessions
// DIVERGE, the decoded TEXT at those points, fan-out (leaves) per node, and
// collapsible branches with connector rails.
//
// Data stays granular (one node per block hash, O(1) add/remove). Everything
// visual — run-merging, divergence, prune/dim — is derived at draw time, so
// live events never do split/merge bookkeeping. Collapse is pure UI state
// (a set of branch-root hashes) and is orthogonal to the tree operations.
const $ = (s) => document.querySelector(s);
const n = (x) => x.toLocaleString("en-US");
const SHORT = { full_attention: "FA", sliding_window: "SWA", mamba: "Mamba",
  mla: "MLA", chunked_local: "Local" };
const DENSE = new Set(["FA", "MLA"]);          // authoritative for the backbone
const FRAME_MS = 450;

const state = {
  nodes: new Map(),      // hash -> { h, parentH, groups:Set, sessions:Set }
  groupType: new Map(),  // group_idx -> short attention tag
  content: {},           // hash -> decoded text
  sessions: [],          // [{id, label}]
  blockSize: 128,
};
const collapsed = new Set(); // branch-root hashes the user collapsed (UI state)

const typesOf = (nd) => new Set([...nd.groups].map((g) => state.groupType.get(g) ?? "?"));
const sessKey = (nd) => [...nd.sessions].sort((a, b) => a - b).join(",");
const sessLabel = (id) => state.sessions[id]?.label ?? `session ${id + 1}`;
const mergeKey = (nd) => `${sessKey(nd)}|${[...typesOf(nd)].sort().join("+")}|${nd.groups.size === 0}`;
const snippet = (h) => (state.content[h] || "").replace(/\s+/g, " ").trim();
function sessColor(sessions) {
  if (sessions.size === 0) return "var(--evicted)";
  if (sessions.size > 1) return "var(--shared)";
  return `var(--sess-${[...sessions][0] % 6})`;
}
function sessText(sessions) {
  if (sessions.size === 0) return "evicted";
  if (sessions.size > 1) return `Reused · ${sessions.size} sessions`;
  return sessLabel([...sessions][0]);
}

// ---- event application (O(1) per block) ----
function applyEvent(e, sess) {
  if (e.k === "c") return void state.nodes.clear();
  if (e.k === "s") {
    const dense = DENSE.has(state.groupType.get(e.g));
    let parent = e.p;
    for (const h of e.h) {
      let nd = state.nodes.get(h);
      if (!nd) { nd = { h, parentH: parent, groups: new Set(), sessions: new Set() }; state.nodes.set(h, nd); }
      if (dense || nd.parentH == null) nd.parentH = parent;
      nd.groups.add(e.g);
      nd.sessions.add(sess);
      parent = h;
    }
  } else if (e.k === "r") {
    for (const h of e.h) {
      const nd = state.nodes.get(h);
      if (nd) e.g == null ? nd.groups.clear() : nd.groups.delete(e.g);
    }
  }
}

// ---- tree helpers ----
function childrenIndex() {
  const kids = new Map();
  for (const [h, nd] of state.nodes)
    if (nd.parentH != null && state.nodes.has(nd.parentH))
      (kids.get(nd.parentH) ?? kids.set(nd.parentH, []).get(nd.parentH)).push(h);
  return kids;
}
function gc() { // evicted leaf -> prune (cascade); evicted w/ children -> keep (dim)
  let changed = true;
  while (changed) {
    changed = false;
    const kids = childrenIndex();
    for (const [h, nd] of state.nodes)
      if (nd.groups.size === 0 && !kids.has(h)) { state.nodes.delete(h); changed = true; }
  }
}
function subtreeSizes(kids) {
  const size = new Map(), busy = new Set();
  const calc = (h) => {
    if (size.has(h)) return size.get(h);
    if (busy.has(h)) return 0; // cycle guard (malformed parent data)
    busy.add(h);
    let s = 1;
    for (const c of kids.get(h) || []) s += calc(c);
    busy.delete(h);
    return size.set(h, s), s;
  };
  for (const h of state.nodes.keys()) calc(h);
  return size;
}
function leafCount(kids, h, memo = new Map(), busy = new Set()) {
  if (memo.has(h)) return memo.get(h);
  if (busy.has(h)) return 0; // cycle guard
  busy.add(h);
  const cs = kids.get(h) || [];
  const l = cs.length === 0 ? 1 : cs.reduce((a, c) => a + leafCount(kids, c, memo, busy), 0);
  busy.delete(h);
  return memo.set(h, l), l;
}

// ---- draw: build nested DOM (Reddit-style threads) from the granular tree ----
function draw() {
  gc();
  const kids = childrenIndex();
  const size = subtreeSizes(kids);
  const seen = new Set();
  const tree = $("#tree");
  tree.replaceChildren();
  for (const [h, nd] of state.nodes)
    if ((nd.parentH == null || !state.nodes.has(nd.parentH)) && !seen.has(h))
      buildChain(h, tree, seen, kids, size);
  updateStats(kids, size);
}

// Walk a linear chain into `container`, merging same-key blocks and absorbing
// turn-boundary stubs; at a real fork, nest each branch in its own collapsible
// thread (a border-left rail). Continuation of a *different* key stays in the
// same container (a type change is not a new thread).
function buildChain(startH, container, seen, kids, size, ctxSessKey = "") {
  let h = startH;
  while (h != null && !seen.has(h)) {
    const run = [h]; seen.add(h);
    const runStubs = [];
    let cur = h;
    const key = mergeKey(state.nodes.get(h));
    let reals;
    while (true) {
      const cs = (kids.get(cur) || []).filter((c) => !seen.has(c));
      const stubs = cs.filter((c) => size.get(c) === 1);
      reals = cs.filter((c) => size.get(c) > 1);
      if (reals.length === 1 && mergeKey(state.nodes.get(reals[0])) === key) {
        stubs.forEach((s) => { runStubs.push(s); seen.add(s); });
        run.push(reals[0]); seen.add(reals[0]); cur = reals[0];
        continue;
      }
      stubs.forEach((s) => { runStubs.push(s); seen.add(s); });
      break;
    }
    container.appendChild(pillEl(run, runStubs, leafCount(kids, cur), ctxSessKey));

    if (reals.length === 1) { h = reals[0]; continue; }   // type change → same thread
    if (reals.length > 1) {                               // real divergence → threads
      reals.sort((a, b) => size.get(b) - size.get(a));
      container.appendChild(divergeEl(reals.length));
      for (const c of reals) {
        const isOpen = !collapsed.has(c);
        const { wrap, body } = branchEl(c, size.get(c), leafCount(kids, c), isOpen);
        container.appendChild(wrap);
        // inside a branch, pills inherit its session, so they omit the label
        if (isOpen) buildChain(c, body, seen, kids, size, sessKey(state.nodes.get(c)));
      }
    }
    return;
  }
}

function pillEl(run, stubs, leaves, ctxSessKey = "") {
  const nd = state.nodes.get(run[0]);
  const pill = document.createElement("div");
  const sh = nd.sessions.size > 1, ev = nd.groups.size === 0;
  pill.className = `pill${sh ? " shared" : ""}${ev ? " evicted" : ""}`;
  pill.style.setProperty("--c", sessColor(nd.sessions));
  const atype = [...typesOf(nd)].sort().join("+") || "—";
  const head = document.createElement("div");
  head.className = "pill-head";
  // The session label is redundant inside its own thread (the branch header +
  // rail already say it); only show it where it adds info (reused/shared, or a
  // block whose session differs from the surrounding thread).
  const showWho = sessKey(nd) !== ctxSessKey;
  head.innerHTML =
    (showWho ? `<span class="who">${sessText(nd.sessions)}</span>` : "") +
    `<span class="atype">${atype}</span>` +
    `<span class="count mono">×${run.length}</span>` +
    `<span class="toks mono">${n(run.length * state.blockSize)} tok</span>` +
    `<span class="leaves mono" title="leaf paths under this node">⌂ ${n(leaves)}</span>`;
  pill.appendChild(head);
  const snip = snippet(run[0]);
  if (snip) {
    const s = document.createElement("div");
    s.className = "snippet";
    s.textContent = snip.slice(0, 160);
    pill.appendChild(s);
  }
  if (stubs.length) {
    const st = document.createElement("button");
    st.className = "stubnote";
    st.textContent = `↳ ${stubs.length} turn-boundary block${stubs.length > 1 ? "s" : ""}`;
    st.onclick = (e) => { e.stopPropagation(); showBlocks("Turn-boundary blocks", stubs); };
    pill.appendChild(st);
  }
  pill.onclick = () => showBlocks(`${sessText(nd.sessions)} · ${atype}`, run);
  return pill;
}

function divergeEl(nPaths) {
  const el = document.createElement("div");
  el.className = "diverge";
  el.innerHTML = `<span class="fork">⑂</span> reused prefix ends — splits into ${nPaths} paths`;
  return el;
}

function branchEl(rootHash, blocks, leaves, isOpen) {
  const nd = state.nodes.get(rootHash);
  const color = sessColor(nd.sessions);
  const wrap = document.createElement("div");
  wrap.className = "branch" + (isOpen ? "" : " collapsed");
  const head = document.createElement("div");
  head.className = "branch-head";
  head.style.setProperty("--c", color);
  head.innerHTML =
    `<span class="caret">${isOpen ? "▾" : "▸"}</span>` +
    `<span class="btag">${sessText(nd.sessions)}</span>` +
    `<span class="bmeta mono">${n(blocks)} blocks · ${n(leaves)} leaves${isOpen ? "" : " · hidden"}</span>`;
  head.onclick = () => { collapsed.has(rootHash) ? collapsed.delete(rootHash) : collapsed.add(rootHash); draw(); };
  const body = document.createElement("div");
  body.className = "branch-body";
  body.style.setProperty("--c", color);   // the connector rail color
  wrap.append(head, body);
  return { wrap, body };
}

function updateStats(kids, size) {
  let sharedBlocks = 0, total = 0, dim = 0, div = 0;
  for (const [h, nd] of state.nodes) {
    total++;
    if (nd.groups.size === 0) dim++;
    if (nd.sessions.size > 1) sharedBlocks++;
    const reals = (kids.get(h) || []).filter((c) => size.get(c) > 1);
    if (reals.length > 1) div++;
  }
  $("#stats").innerHTML =
    `<span><b>${n(sharedBlocks)}</b> reused blocks (${n(sharedBlocks * state.blockSize)} tok)</span>` +
    `<span><b>${n(div)}</b> divergence point${div === 1 ? "" : "s"}</span>` +
    `<span><b>${n(total)}</b> blocks total</span>` +
    (dim ? `<span><b>${n(dim)}</b> dimmed</span>` : "");
}

function showBlocks(title, hashes) {
  $("#detail").hidden = false;
  $("#detail-title").textContent =
    `${title} · ${hashes.length} block${hashes.length > 1 ? "s" : ""} · ${n(hashes.length * state.blockSize)} tok`;
  $("#detail-body").replaceChildren(...hashes.map((h, i) => {
    const el = document.createElement("div");
    el.className = "blk";
    const head = document.createElement("div");
    head.className = "h";
    head.textContent = `block ${i + 1} · #${h.slice(0, 10)}`;
    el.appendChild(head);
    const text = state.content[h];
    if (text) {
      const p = document.createElement("div");
      p.className = "prev";
      p.textContent = text;
      el.appendChild(p);
    }
    return el;
  }));
}

// ---- load + transport ----
async function main() {
  const src = new URLSearchParams(location.search).get("data") || "kv_events.json";
  const run = await (await fetch(src)).json();
  state.content = run.content || {};
  state.blockSize = run.meta.block_size;
  state.sessions = run.meta.sessions || [];
  for (const g of run.meta.groups) state.groupType.set(g.id, SHORT[g.attention_type] ?? "?");
  buildLegend();
  $("#meta-line").textContent =
    `${run.meta.model} · ${state.sessions.length} sessions · ${run.meta.groups.length} KV groups · block ${run.meta.block_size}`;

  const frames = run.frames;
  const seekTo = (t) => {
    state.nodes.clear();
    for (let i = 0; i <= t && i < frames.length; i++)
      for (const e of frames[i].ev) applyEvent(e, frames[i].s ?? 0);
    draw();
    $("#scrub").value = t;
    $("#step-label").textContent = `frame ${t + 1} / ${frames.length}`;
  };
  $("#scrub").max = frames.length - 1;
  makeTransport(frames.length, seekTo);
}

function buildLegend() {
  const items = state.sessions.map((s) => [`sess-${s.id % 6}`, s.label]);
  items.push(["shared", "reused (≥2 sessions)"]);
  $("#legend").replaceChildren(...items.map(([k, txt]) => {
    const s = document.createElement("span");
    const i = document.createElement("i");
    i.style.background = `var(--${k})`;
    s.append(i, txt);
    return s;
  }));
}

function makeTransport(nFrames, seek) {
  const playBtn = $("#play"), scrub = $("#scrub"), body = document.body;
  let t = 0, timer = null;
  const go = (v) => { t = Math.max(0, Math.min(nFrames - 1, v)); seek(t); };
  const stop = () => { clearInterval(timer); timer = null; playBtn.textContent = "▶"; body.classList.remove("playing"); };
  const play = () => {
    if (t >= nFrames - 1) go(0);
    playBtn.textContent = "❚❚"; body.classList.add("playing");
    timer = setInterval(() => (t >= nFrames - 1 ? stop() : go(t + 1)), FRAME_MS);
  };
  playBtn.onclick = () => (timer ? stop() : play());
  scrub.oninput = () => { stop(); go(+scrub.value); };
  $("#detail-close").onclick = () => ($("#detail").hidden = true);
  const p = new URLSearchParams(location.search).get("f");
  if (p != null) { go(+p); return; }
  go(0); play();
}

main();
