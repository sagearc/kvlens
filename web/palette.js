// Single source of truth for identity color. Hex values live as CSS custom
// properties in style.css (light/dark swap in one place); here we map a
// semantic key to its var(). Color follows the entity (a session), never rank.

const SESSION_SLOTS = 6;

export function sessionColor(i) {
  return i < SESSION_SLOTS ? `var(--s${i})` : "var(--muted)";
}
