import type { View } from "./view";

const NAV: { key: View; label: string; glyph: string }[] = [
  { key: "map", label: "Карта", glyph: "▦" },
  { key: "recs", label: "Рекомендации", glyph: "✷" },
  { key: "favorites", label: "Избранное", glyph: "♥" },
  { key: "profile", label: "Профиль", glyph: "◑" },
];

export function Sidebar({
  open,
  view,
  favCount = 0,
  onSelect,
  onClose,
}: {
  open: boolean;
  view: View;
  favCount?: number;
  onSelect: (v: View) => void;
  onClose: () => void;
}) {
  return (
    <div className={`drawer${open ? " drawer--open" : ""}`} onClick={onClose}>
      <aside className="drawer__panel" onClick={(e) => e.stopPropagation()}>
        <div className="drawer__brand">
          <span className="brand-o">о</span>крест
        </div>
        <nav className="drawer__nav">
          {NAV.map((n) => (
            <button
              key={n.key}
              type="button"
              className={`navitem${view === n.key ? " navitem--active" : ""}`}
              onClick={() => onSelect(n.key)}
            >
              <span className="navitem__glyph">{n.glyph}</span>
              {n.label}
              {n.key === "favorites" && favCount > 0 && <span className="navitem__badge">{favCount}</span>}
            </button>
          ))}
        </nav>
        <div className="drawer__foot">Москва · события рядом</div>
      </aside>
    </div>
  );
}
