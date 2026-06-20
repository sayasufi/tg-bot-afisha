import { useRef } from "react";

import type { ThemeName } from "../../lib/telegram";
import { useFocusTrap } from "../../lib/useFocusTrap";
import type { View } from "./view";

const NAV: { key: View; label: string; glyph: string }[] = [
  { key: "map", label: "Карта", glyph: "▦" },
  { key: "recs", label: "Подборка", glyph: "✷" },
  { key: "favorites", label: "Избранное", glyph: "♥" },
  { key: "venues", label: "Площадки", glyph: "⌂" },
  { key: "profile", label: "Профиль", glyph: "◑" },
];

export function Sidebar({
  open,
  view,
  favCount = 0,
  theme = "light",
  onToggleTheme,
  onSelect,
  onClose,
}: {
  open: boolean;
  view: View;
  favCount?: number;
  theme?: ThemeName;
  onToggleTheme?: () => void;
  onSelect: (v: View) => void;
  onClose: () => void;
}) {
  const dark = theme === "dark";
  const panelRef = useRef<HTMLElement>(null);
  useFocusTrap(panelRef, open); // contain keyboard focus in the menu while it's open
  return (
    <div className={`drawer${open ? " drawer--open" : ""}`} onClick={onClose}>
      <aside
        className="drawer__panel"
        onClick={(e) => e.stopPropagation()}
        ref={panelRef}
        tabIndex={-1}
        role="dialog"
        aria-modal="true"
        aria-label="Меню"
      >
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
        <button
          type="button"
          className={`themetoggle${dark ? " themetoggle--dark" : ""}`}
          onClick={onToggleTheme}
          role="switch"
          aria-checked={dark}
        >
          <span className="themetoggle__label">
            <span className="themetoggle__glyph">{dark ? "☾" : "☀"}</span>
            {dark ? "После заката" : "Дневной свет"}
          </span>
          <span className="themetoggle__switch">
            <span className="themetoggle__knob" />
          </span>
        </button>
        <div className="drawer__foot">события рядом с тобой</div>
      </aside>
    </div>
  );
}
