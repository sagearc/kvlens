// Radix-tree tab — a thin painter over a view-model computed in Python.
//
// All derivation (run-merging, divergence, prune/dim, leaf counts) now lives in
// src/kvlens/tree.py; the browser only walks the ready-made nested structure and
// builds DOM. The frame's view-model shape is documented in the README /
// AGENTS.md §8. Collapse and the detail drawer are the only client-side state.
//
// ($ and n are the project's shared DOM/number helpers from util.js, used the
// same way in app.js.)
import { $, n, loadData } from "./util.js";
import { makeTransport, makeLiveTransport } from "./transport.js";

const FRAME_MS = 450;
const collapsedBranches = new Set(); // branch-root hashes the user collapsed
let content = {}; // block hash -> decoded text (for the drawer)
let blockSize = 128;
let currentViewModel = null; // frame in view — repaint target when collapsing

const makeElement = (tag, className, text) => {
  const element = document.createElement(tag);
  if (className) element.className = className;
  if (text != null) element.textContent = text;
  return element;
};
const colorVar = (token) => `var(--${token})`; // semantic token -> CSS custom prop

// ---- paint ----
function paint(viewModel) {
  const tree = $("#tree");
  tree.replaceChildren();
  renderItems(tree, viewModel.roots);
  renderStats(viewModel.stats);
  renderLegend(viewModel.legend);
}

function renderItems(container, items) {
  for (const item of items) container.appendChild(renderItem(item));
}

function renderItem(item) {
  if (item.kind === "run") return renderPill(item);
  if (item.kind === "diverge") return renderDivergence(item.paths);
  return renderBranch(item);
}

function renderPill(pillData) {
  const classNames = `pill${pillData.shared ? " shared" : ""}${pillData.evicted ? " evicted" : ""}`;
  const pill = makeElement("div", classNames);
  pill.style.setProperty("--c", colorVar(pillData.color));

  const head = makeElement("div", "pill-head");
  if (pillData.showWho) head.appendChild(makeElement("span", "who", pillData.who));
  for (const attentionType of pillData.types) {
    head.appendChild(makeElement("span", "atype", attentionType));
  }
  head.appendChild(makeElement("span", "count mono", `×${pillData.count}`));
  head.appendChild(makeElement("span", "toks mono", `${n(pillData.toks)} tok`));
  const leaves = makeElement("span", "leaves mono", `⌂ ${n(pillData.leaves)}`);
  leaves.title = "leaf paths under this node";
  head.appendChild(leaves);
  pill.appendChild(head);

  if (pillData.snippet) pill.appendChild(makeElement("div", "snippet", pillData.snippet));
  if (pillData.stubCount) {
    const label = `↳ ${pillData.stubCount} turn-boundary block${pillData.stubCount > 1 ? "s" : ""}`;
    const stubButton = makeElement("button", "stubnote", label);
    stubButton.onclick = (event) => {
      event.stopPropagation();
      showBlocks("Turn-boundary blocks", pillData.stubBlocks);
    };
    pill.appendChild(stubButton);
  }

  const drawerTitle =
    `${pillData.who}${pillData.types.length ? " · " + pillData.types.join(", ") : ""}`;
  pill.onclick = () => showBlocks(drawerTitle, pillData.blocks);
  return pill;
}

function renderDivergence(pathCount) {
  const divergence = makeElement("div", "diverge");
  divergence.appendChild(makeElement("span", "fork", "⑂"));
  divergence.append(` reused prefix ends — splits into ${pathCount} paths`);
  return divergence;
}

function renderBranch(branchData) {
  const isOpen = !collapsedBranches.has(branchData.rootHash);
  const branch = makeElement("div", "branch" + (isOpen ? "" : " collapsed"));

  const head = makeElement("div", "branch-head");
  head.style.setProperty("--c", colorVar(branchData.color));
  head.appendChild(makeElement("span", "caret", isOpen ? "▾" : "▸"));
  head.appendChild(makeElement("span", "btag", branchData.who));
  const meta =
    `${n(branchData.blockCount)} blocks · ${n(branchData.leaves)} ` +
    `leaf${branchData.leaves === 1 ? "" : "s"}${isOpen ? "" : " · hidden"}`;
  head.appendChild(makeElement("span", "bmeta mono", meta));
  head.onclick = () => {
    if (collapsedBranches.has(branchData.rootHash)) {
      collapsedBranches.delete(branchData.rootHash);
    } else {
      collapsedBranches.add(branchData.rootHash);
    }
    paint(currentViewModel);
  };

  const body = makeElement("div", "branch-body");
  body.style.setProperty("--c", colorVar(branchData.color));
  renderItems(body, branchData.body);
  branch.append(head, body);
  return branch;
}

function renderStats(stats) {
  $("#stats").innerHTML =
    `<span><b>${n(stats.sharedBlocks)}</b> reused blocks (${n(stats.sharedBlocks * blockSize)} tok)</span>` +
    `<span><b>${n(stats.divergences)}</b> divergence point${stats.divergences === 1 ? "" : "s"}</span>` +
    `<span><b>${n(stats.total)}</b> blocks total</span>` +
    (stats.dim ? `<span><b>${n(stats.dim)}</b> dimmed</span>` : "");
}

function renderLegend(entries) {
  $("#legend").replaceChildren(...entries.map((entry) => {
    const span = makeElement("span");
    const swatch = makeElement("i");
    swatch.style.background = colorVar(entry.token);
    span.append(swatch, entry.label);
    return span;
  }));
}

// ---- detail drawer (client UI) ----
function showBlocks(title, blocks) {
  $("#detail").hidden = false;
  $("#detail-title").textContent =
    `${title} · ${blocks.length} block${blocks.length > 1 ? "s" : ""} · ${n(blocks.length * blockSize)} tok`;
  $("#detail-body").replaceChildren(...blocks.map(([blockHash, attentionType], index) => {
    const block = makeElement("div", "blk");
    block.appendChild(
      makeElement("div", "h", `block ${index + 1} · ${attentionType} · #${blockHash.slice(0, 10)}`)
    );
    const text = content[blockHash];
    if (text) block.appendChild(makeElement("div", "prev", text));
    return block;
  }));
}

function setMeta(meta) {
  blockSize = meta.block_size;
  $("#meta-line").innerHTML =
    `<span class="id">${meta.model.split("/").pop()}</span> · ` +
    `${meta.groups.length} KV groups · block ${meta.block_size}`;
}

// ---- load + transport ----
async function main() {
  $("#detail-close").onclick = () => ($("#detail").hidden = true);

  // `?live` (optionally `?live=<url>`) streams from the Python SSE server; the
  // same painter renders each pushed frame. Otherwise replay the static file.
  const liveParam = new URLSearchParams(location.search).get("live");
  if (liveParam != null) {
    content = {};
    makeLiveTransport({
      url: liveParam && liveParam !== "1" ? liveParam : "/events",
      onMeta: setMeta,
      onFrame: (message, frameIndex) => {
        Object.assign(content, message.contentDelta || {});
        currentViewModel = message.vm;
        paint(currentViewModel);
        $("#step-label").textContent = `frame ${frameIndex + 1} · live`;
      },
    });
    return;
  }

  const artifact = await loadData("kv_events.json");
  content = artifact.content || {};
  setMeta(artifact.meta);
  const frames = artifact.frames;
  makeTransport({
    count: frames.length,
    stepMs: FRAME_MS,
    param: "f",
    onStep: (frameIndex) => {
      currentViewModel = frames[frameIndex].vm;
      paint(currentViewModel);
      $("#step-label").textContent = `frame ${frameIndex + 1} / ${frames.length}`;
    },
  });
}

main();
