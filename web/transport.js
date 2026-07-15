// Shared playback for both tabs: play/pause/scrub, a `?<param>=N` deep link, and
// cross-tab position via sessionStorage. Position is stored as a timeline
// fraction because the tabs differ in length (turns vs frames), so switching
// tabs keeps the same relative point. `onStep(t)` does the tab-specific render.
import { $ } from "./util.js";

export function makeTransport({ count, stepMs, param, onStep }) {
  const playBtn = $("#play"), scrub = $("#scrub"), body = document.body;
  let t = 0, timer = null;
  scrub.max = count - 1;

  const save = () => sessionStorage.setItem("kvviz.play",
    JSON.stringify({ frac: count > 1 ? t / (count - 1) : 0, playing: !!timer }));
  const go = (v) => {
    t = Math.max(0, Math.min(count - 1, v));
    scrub.value = t; onStep(t); save();
  };
  const stop = () => {
    clearInterval(timer); timer = null;
    playBtn.textContent = "▶"; body.classList.remove("playing"); save();
  };
  const play = () => {
    if (t >= count - 1) go(0);
    playBtn.textContent = "❚❚"; body.classList.add("playing");
    timer = setInterval(() => (t >= count - 1 ? stop() : go(t + 1)), stepMs);
    save();
  };
  playBtn.onclick = () => (timer ? stop() : play());
  scrub.oninput = () => { stop(); go(+scrub.value); };
  addEventListener("pagehide", save);

  const dl = new URLSearchParams(location.search).get(param);
  if (dl != null) return void go(+dl);                 // deep-link wins
  const s = JSON.parse(sessionStorage.getItem("kvviz.play") || "null");
  if (s) { go(Math.round(s.frac * (count - 1))); if (s.playing) play(); return; }
  go(0); play();                                       // first visit → autostart
}

// Live playback over SSE: frames arrive from the Python server (replay or live
// vLLM) instead of a static file. Same render path — `onFrame(msg, i)` mirrors
// the file mode's `onStep(t)`. A `meta` message arrives first, then `frame`s.
export function makeLiveTransport({ url, onMeta, onFrame }) {
  const body = document.body;
  body.classList.add("playing");
  const eventSource = new EventSource(url);
  let frameIndex = 0;
  eventSource.onmessage = (event) => {
    const message = JSON.parse(event.data);
    if (message.type === "meta") onMeta(message.meta);
    else if (message.type === "frame") onFrame(message, frameIndex++);
  };
  // Stream end / drop is normal — stop the pulse; keep the last frame on screen.
  eventSource.onerror = () => {
    eventSource.close();
    body.classList.remove("playing");
  };
}
