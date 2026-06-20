import { useRef } from "react";

import type { TgUser } from "../../lib/telegram";
import { safeHttpUrl } from "../../lib/url";
import { useFocusTrap } from "../../lib/useFocusTrap";
import type { View } from "./view";

const NAV: { key: View; label: string; glyph: string }[] = [
  { key: "map", label: "Карта", glyph: "▦" },
  { key: "recs", label: "Подборка", glyph: "✷" },
  { key: "favorites", label: "Избранное", glyph: "♥" },
  { key: "venues", label: "Площадки", glyph: "⌂" },
];

export function Sidebar({
  open,
  view,
  favCount = 0,
  user = null,
  onSelect,
  onClose,
}: {
  open: boolean;
  view: View;
  favCount?: number;
  user?: TgUser | null;
  onSelect: (v: View) => void;
  onClose: () => void;
}) {
  const navCount: Partial<Record<View, number>> = { favorites: favCount };
  // The «Профиль» nav item is gone; this account block at the bottom is the entry to the profile
  // screen (where notifications / city / taste live) — Linear/Slack-style.
  const name = user ? [user.first_name, user.last_name].filter(Boolean).join(" ") || "Гость" : "Гость";
  const handle = user?.username ? `@${user.username}` : "Telegram";
  const avatarUrl = safeHttpUrl(user?.photo_url);
  const initial = (name[0] || "?").toUpperCase();
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
              {(navCount[n.key] ?? 0) > 0 && <span className="navitem__badge">{navCount[n.key]}</span>}
            </button>
          ))}
        </nav>
        <button
          type="button"
          className={`drawer__account${view === "profile" ? " drawer__account--active" : ""}`}
          onClick={() => onSelect("profile")}
          aria-label="Профиль и настройки"
        >
          <span
            className="drawer__avatar"
            style={avatarUrl ? { backgroundImage: `url("${avatarUrl}")` } : undefined}
          >
            {avatarUrl ? "" : initial}
          </span>
          <span className="drawer__handle">{handle}</span>
          <span className="drawer__account-go" aria-hidden="true">›</span>
        </button>
        <div className="drawer__foot">события рядом с тобой</div>
      </aside>
    </div>
  );
}
