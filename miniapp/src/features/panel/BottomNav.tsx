import type { View } from "./view";

// Primary navigation as a flat bottom plinth — so Подборка / Избранное / Профиль are
// discoverable from the map instead of buried behind the ☰ drawer. Square, hairline-
// divided cells; the active cell wears the one acid marker.
const NAV: { key: View; label: string; glyph: string }[] = [
  { key: "map", label: "Карта", glyph: "▦" },
  { key: "recs", label: "Подборка", glyph: "✷" },
  { key: "favorites", label: "Избранное", glyph: "♥" },
  { key: "profile", label: "Профиль", glyph: "◑" },
];

export function BottomNav({
  view,
  favCount = 0,
  onSelect,
}: {
  view: View;
  favCount?: number;
  onSelect: (v: View) => void;
}) {
  return (
    <nav className="bottomnav" aria-label="Разделы">
      {NAV.map((n) => (
        <button
          key={n.key}
          type="button"
          className={`bottomnav__item${view === n.key ? " bottomnav__item--active" : ""}`}
          aria-current={view === n.key ? "page" : undefined}
          onClick={() => onSelect(n.key)}
        >
          <span className="bottomnav__glyph" aria-hidden="true">
            {n.glyph}
          </span>
          <span className="bottomnav__label">{n.label}</span>
          {n.key === "favorites" && favCount > 0 && <span className="bottomnav__badge">{favCount}</span>}
        </button>
      ))}
    </nav>
  );
}
