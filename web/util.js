// Small shared helpers used by both tabs.
export const $ = (s) => document.querySelector(s);
export const n = (x) => x.toLocaleString("en-US");
export const pct = (x) => `${Math.round(x * 100)}%`;

// Load the tab's data: a `?data=` override (local captures) or the committed sample.
export async function loadData(fallback) {
  const src = new URLSearchParams(location.search).get("data") || fallback;
  return (await fetch(src)).json();
}
