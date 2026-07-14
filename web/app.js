// Plays a captured Codex-trace run turn by turn (~2s each) for a live feel.
// Every number is the engine's; this file only maps turn state -> DOM.
import { sessionColor } from "./palette.js";
import { $, n, pct, loadData } from "./util.js";
import { makeTransport } from "./transport.js";

const tpl = (id) => document.getElementById(id).content.firstElementChild;
// The dataset redacts prose to lorem-ipsum; collapse each such run to a marker
// so the real content (commands, paths) stays legible.
const cleanText = (s) => s.replace(/lorem ipsum(?:(?!\n\n)[\s\S])*/gi, "⟨redacted prose⟩");
const STEP_MS = 500; // 0.5 seconds per turn
// Deterministic per-session faces (DiceBear); avatars are per session, not per
// message, so only a handful load and each is browser-cached. Falls back to a
// colored initial circle if offline (see img.onerror).
const AVATAR_STYLE = "avataaars";
const avatarUrl = (seed) =>
  `https://api.dicebear.com/9.x/${AVATAR_STYLE}/svg?seed=${encodeURIComponent(seed)}`;

const TILES = [
  { key: "ctx", label: "Context length", val: (t) => n(t.context_tokens), note: () => "tokens in prompt" },
  { key: "new", label: "New this turn", val: (t) => n(t.new_tokens), note: () => "prefilled (real cost)" },
  { key: "cached", label: "Cached this turn", val: (t) => n(t.cached_tokens), note: () => "reused from cache" },
  { key: "turnhit", label: "Turn hit rate", val: (t) => pct(t.turn_hit_rate), note: () => "this prompt" },
  { key: "usage", label: "KV cache usage", val: (t, m) => pct(t.kv_usage),
    note: (t, m) => `${n(t.blocks_used)} / ${n(m.num_blocks)} blocks` },
];

async function main() {
  const run = await loadData("run.json");
  const { meta, groups, sessions, turns } = run;

  const shortModel = meta.model.split("/").pop();
  $("#meta-line").innerHTML =
    `<span class="id">${shortModel}</span> · ${meta.dataset.traces} traces · ` +
    `capped at ${Math.round(meta.max_model_len / 1024)}K tokens`;
  $("#groups-line").textContent = groupsSummary(groups, meta);
  const tileRefs = buildTiles();
  const chat = makeChatView(turns, sessions);

  const render = (t) => {
    const turn = turns[t];
    $("#hit-rate").textContent = pct(turn.cum_hit_rate);
    $("#hit-note").textContent =
      `cumulative over ${t + 1} turn${t ? "s" : ""} · ${sessions[turn.session].label}`;
    for (const tile of TILES) {
      const el = tileRefs[tile.key];
      const next = tile.val(turn, meta);
      if (el.dataset.v !== undefined && el.dataset.v !== next) flash(el);
      el.dataset.v = next;
      el.textContent = next;
      el.nextElementSibling.textContent = tile.note(turn, meta);
    }
    renderLegend(turns, sessions, t);
    drawSpark(turns, sessions, t);
    chat.upTo(t);
    $("#step-label").textContent = `turn ${t + 1} / ${turns.length}`;
  };

  makeTransport({ count: turns.length, stepMs: STEP_MS, param: "t", onStep: render });
}

function groupsSummary(groups, meta) {
  const counts = {};
  for (const g of groups) counts[g.attention_type] = (counts[g.attention_type] || 0) + 1;
  const parts = Object.entries(counts).map(([k, v]) => `${v}× ${k.replace(/_/g, "-")}`);
  return `${parts.join(" · ")} · block ${meta.block_size}`;
}

function buildTiles() {
  const host = $("#tiles");
  const refs = {};
  for (const tile of TILES) {
    const el = tpl("tile-tpl").cloneNode(true);
    el.querySelector(".tile-label").textContent = tile.label;
    host.appendChild(el);
    refs[tile.key] = el.querySelector(".tile-value");
  }
  return refs;
}

// Live legend: only sessions that have arrived by turn `upto`, each showing its
// context so far (never the final size — that would reveal the future).
function renderLegend(turns, sessions, upto) {
  const cur = new Map();
  for (const t of turns) if (t.t <= upto) cur.set(t.session, t.context_tokens);
  $("#legend").replaceChildren(...sessions.filter((s) => cur.has(s.id)).map((s) => {
    const el = document.createElement("span");
    const dot = document.createElement("i");
    dot.style.background = sessionColor(s.id);
    el.append(dot, `${s.label} · ${n(cur.get(s.id))} tok`);
    return el;
  }));
}

let flashTimer = new WeakMap();
function flash(el) {
  el.classList.add("flash");
  clearTimeout(flashTimer.get(el));
  flashTimer.set(el, setTimeout(() => el.classList.remove("flash"), 260));
}

// --- sparkline: context tokens (y) over play order (x), one line per session ---
const VB_W = 1000, VB_H = 400, PAD = 12;
function drawSpark(turns, sessions, upto) {
  const svg = $("#spark");
  svg.setAttribute("viewBox", `0 0 ${VB_W} ${VB_H}`);
  svg.setAttribute("preserveAspectRatio", "none");
  const N = turns.length;
  // Axis scales to the largest context seen SO FAR, so it grows live rather
  // than being pre-scaled to the (future) final maximum.
  const maxCtx = Math.max(1, ...turns.filter((t) => t.t <= upto).map((t) => t.context_tokens));
  const x = (t) => (N === 1 ? 0 : (t / (N - 1)) * VB_W);
  const y = (v) => VB_H - PAD - (v / maxCtx) * (VB_H - 2 * PAD);

  const parts = [];
  for (const s of sessions) {
    const pts = turns.filter((t) => t.session === s.id && t.t <= upto)
      .map((t) => `${x(t.t).toFixed(1)},${y(t.context_tokens).toFixed(1)}`);
    if (pts.length) {
      parts.push(`<polyline fill="none" stroke="${sessionColor(s.id)}" stroke-width="2"
        vector-effect="non-scaling-stroke" stroke-linejoin="round" points="${pts.join(" ")}"/>`);
      const [lx, ly] = pts[pts.length - 1].split(",");
      parts.push(`<circle cx="${lx}" cy="${ly}" r="3.5" fill="${sessionColor(s.id)}"
        vector-effect="non-scaling-stroke"/>`);
    }
  }
  parts.push(`<line x1="${x(upto)}" y1="0" x2="${x(upto)}" y2="${VB_H}"
    stroke="var(--muted)" stroke-width="1" vector-effect="non-scaling-stroke" opacity="0.4"/>`);
  svg.innerHTML = parts.join("");
}

// --- chat: reveal turns up to t; append forward, rebuild on backward scrub ---
function makeChatView(turns, sessions) {
  const log = $("#chat-log");
  let idx = 0, shown = -1;
  const cards = [];

  const build = (turn) => {
    const el = tpl("turn-tpl").cloneNode(true);
    const color = sessionColor(turn.session);
    el.style.setProperty("--sess", color);
    const label = sessions[turn.session].label;
    const traceNum = (label.match(/\d+/) || [""])[0];

    const av = el.querySelector(".avatar");
    av.style.background = color;
    av.querySelector(".badge").textContent = traceNum;  // session id on the circle
    const img = new Image();
    img.alt = ""; img.loading = "lazy";
    img.onerror = () => img.remove();  // offline: tinted circle + id badge remain
    img.src = avatarUrl(label);
    av.appendChild(img);

    // avatar (face + color + id badge) carries identity, so the header only
    // needs the message-specific info — no redundant "trace #N".
    el.querySelector(".who").textContent = `turn ${turn.turn + 1}`;
    el.querySelector(".when").textContent = `${pct(turn.turn_hit_rate)} cached`;

    const total = turn.cached_tokens + turn.new_tokens || 1;
    el.querySelector(".seg.cached").style.flexGrow = turn.cached_tokens / total;
    el.querySelector(".seg.new").style.flexGrow = turn.new_tokens / total;
    el.querySelector(".lbl-cached").textContent = `${n(turn.cached_tokens)} cached`;
    el.querySelector(".lbl-new").textContent = `${n(turn.new_tokens)} new`;

    const human = { ...turn.human, text: cleanText(turn.human.text) };
    setupText(el.querySelector(".ask"), el.querySelector(".ask-more"), human, "show more");
    const reply = el.querySelector(".reply");
    if (/^lorem ipsum/i.test(turn.gpt.text)) {  // dataset redacts assistant turns
      reply.textContent = `↳ assistant reply redacted in dataset (${n(turn.gpt.tokens)} placeholder tokens)`;
      reply.classList.remove("clamp");
      reply.classList.add("redacted");
    } else {
      setupText(reply, el.querySelector(".reply-more"), turn.gpt, "show output");
    }
    log.prepend(el);  // newest on top, always in view
    cards.push(el);
  };

  return {
    upTo(t) {
      if (t < shown) { log.innerHTML = ""; cards.length = 0; idx = 0; }
      while (idx <= t) build(turns[idx++]);
      cards.forEach((c, i) => c.classList.toggle("active", i === t));
      shown = t;
    },
  };
}

function setupText(el, btn, field, moreLabel) {
  const truncated = field.chars > field.text.length;
  el.textContent = field.text + (truncated ? `\n… (+${n(field.chars - field.text.length)} more chars)` : "");
  // show the toggle only when the text actually overflows the clamp
  requestAnimationFrame(() => {
    if (el.scrollHeight > el.clientHeight + 2) {
      btn.hidden = false;
      btn.onclick = () => {
        const open = el.classList.toggle("clamp") === false;
        btn.textContent = open ? "show less" : moreLabel;
      };
    }
  });
}

main();
