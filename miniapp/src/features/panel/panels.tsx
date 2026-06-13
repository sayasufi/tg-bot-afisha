import type { CSSProperties } from "react";

import type { EventItem } from "../../api/client";
import { eventBucket, formatWhenShort } from "../../lib/datetime";
import { Highlight } from "../../lib/highlight";
import { CategoryIcon } from "../../lib/icons";
import type { TgUser } from "../../lib/telegram";

export type View = "map" | "recs" | "profile";

const NAV: { key: View; label: string; glyph: string }[] = [
  { key: "map", label: "Карта", glyph: "▦" },
  { key: "recs", label: "Рекомендации", glyph: "✷" },
  { key: "profile", label: "Профиль", glyph: "◑" },
];

export function Sidebar({ open, view, onSelect, onClose }: { open: boolean; view: View; onSelect: (v: View) => void; onClose: () => void }) {
  return (
    <div className={`drawer${open ? " drawer--open" : ""}`} onClick={onClose}>
      <aside className="drawer__panel" onClick={(e) => e.stopPropagation()}>
        <div className="drawer__brand">афиша</div>
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
            </button>
          ))}
        </nav>
        <div className="drawer__foot">Москва · события рядом</div>
      </aside>
    </div>
  );
}

function EventRow({
  item,
  index,
  query,
  featured = false,
  onSelect,
}: {
  item: EventItem;
  index: number;
  query?: string;
  featured?: boolean;
  onSelect: (i: EventItem) => void;
}) {
  return (
    <button
      type="button"
      className={`erow${featured ? " erow--featured" : ""}`}
      style={{ "--i": index } as CSSProperties}
      onClick={() => onSelect(item)}
    >
      <span className="erow__mark">
        <CategoryIcon cat={item.category} size={22} />
      </span>
      <span className="erow__body">
        <span className="erow__title">
          <Highlight text={item.title} query={query} />
        </span>
        <span className="erow__meta">
          {formatWhenShort(item.date_start, item.date_end)}
          {item.venue ? ` · ${item.venue}` : ""}
        </span>
      </span>
    </button>
  );
}

export function RecommendationsPanel({
  items,
  query,
  onSelect,
  onClose,
}: {
  items: EventItem[];
  query?: string;
  onSelect: (i: EventItem) => void;
  onClose: () => void;
}) {
  const sorted = [...items].sort((a, b) => (a.date_start || "").localeCompare(b.date_start || ""));
  // Group into time buckets (Сегодня / На этой неделе / Позже / Идут сейчас / Постоянно).
  const groups = new Map<number, { label: string; items: EventItem[] }>();
  for (const it of sorted) {
    const b = eventBucket(it.date_start, it.date_end);
    let g = groups.get(b.order);
    if (!g) {
      g = { label: b.label, items: [] };
      groups.set(b.order, g);
    }
    g.items.push(it);
  }
  const ordered = [...groups.entries()].sort((a, b) => a[0] - b[0]).map(([, g]) => g);
  let idx = 0;

  return (
    <div className="panelview">
      <header className="panelview__head">
        <h2>Рекомендации</h2>
        <button type="button" className="panelview__close" aria-label="Закрыть" onClick={onClose}>
          ✕
        </button>
      </header>
      <div className="panelview__scroll">
        {ordered.length === 0 && <p className="panelview__empty">Пока нечего показать</p>}
        {ordered.map((g) => (
          <section key={g.label}>
            <div className="recs__section">
              {g.label}
              <span className="recs__n">{g.items.length}</span>
            </div>
            {g.items.map((it) => {
              const i = idx++;
              return <EventRow key={it.event_id} item={it} index={i} query={query} featured={i === 0} onSelect={onSelect} />;
            })}
          </section>
        ))}
      </div>
    </div>
  );
}

export function ProfilePanel({
  user,
  total,
  city,
  items,
  favIds,
  onSelect,
  onClose,
}: {
  user: TgUser | null;
  total: number;
  city: string;
  items: EventItem[];
  favIds: Set<string>;
  onSelect: (i: EventItem) => void;
  onClose: () => void;
}) {
  const name = user ? [user.first_name, user.last_name].filter(Boolean).join(" ") || "Гость" : "Гость";
  const initial = (name[0] || "?").toUpperCase();
  const favs = items.filter((it) => favIds.has(it.event_id));
  return (
    <div className="panelview">
      <header className="panelview__head">
        <h2>Профиль</h2>
        <button type="button" className="panelview__close" aria-label="Закрыть" onClick={onClose}>
          ✕
        </button>
      </header>
      <div className="panelview__scroll">
        <div className="profile">
          <div className="profile__avatar" style={user?.photo_url ? { backgroundImage: `url(${user.photo_url})` } : undefined}>
            {user?.photo_url ? "" : initial}
          </div>
          <div className="profile__id">
            <div className="profile__name">{name}</div>
            <div className="profile__handle">{user?.username ? `@${user.username}` : "Telegram"}</div>
          </div>
        </div>
        <div className="profile__rows">
          <div className="profile__row">
            <span>Город</span>
            <b>{city}</b>
          </div>
          <div className="profile__row">
            <span>Событий на карте</span>
            <b>{total}</b>
          </div>
          <div className="profile__row">
            <span>Избранное</span>
            <b>{favIds.size}</b>
          </div>
        </div>

        {favs.length > 0 ? (
          <>
            <div className="recs__section">
              Избранное
              <span className="recs__n">{favs.length}</span>
            </div>
            {favs.map((it, i) => (
              <EventRow key={it.event_id} item={it} index={i} onSelect={onSelect} />
            ))}
          </>
        ) : (
          <p className="panelview__hint">Отмечай события сердечком ♥ в карточке — они появятся здесь. Город меняется в боте командой /city.</p>
        )}
      </div>
    </div>
  );
}
