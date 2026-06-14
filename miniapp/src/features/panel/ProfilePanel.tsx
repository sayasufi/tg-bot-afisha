import type { EventItem } from "../../api/client";
import { categoryMeta } from "../../lib/categories";
import type { LatLon } from "../../lib/distance";
import { IconClose } from "../../lib/icons";
import type { TgUser } from "../../lib/telegram";
import { safeHttpUrl } from "../../lib/url";
import { EventRow } from "./EventRow";

export function ProfilePanel({
  user,
  total,
  city,
  items,
  favIds,
  query,
  userPos,
  onSelect,
  onClose,
}: {
  user: TgUser | null;
  total: number;
  city: string;
  items: EventItem[];
  favIds: Set<string>;
  query?: string;
  userPos?: LatLon | null;
  onSelect: (i: EventItem) => void;
  onClose: () => void;
}) {
  const name = user ? [user.first_name, user.last_name].filter(Boolean).join(" ") || "Гость" : "Гость";
  const initial = (name[0] || "?").toUpperCase();
  const avatarUrl = safeHttpUrl(user?.photo_url);
  const favs = items.filter((it) => favIds.has(it.event_id));

  // "Твой вкус" — the category mix of your favourites, as a proportion bar.
  const taste = (() => {
    const counts = new Map<string, number>();
    for (const it of favs) counts.set(it.category, (counts.get(it.category) || 0) + 1);
    const ranked = [...counts.entries()].sort((a, b) => b[1] - a[1]);
    return ranked.map(([key, n]) => ({ key, n, meta: categoryMeta(key), pct: (n / favs.length) * 100 }));
  })();
  return (
    <div className="panelview">
      <header className="panelview__head">
        <h2>Профиль</h2>
        <button type="button" className="panelview__close" aria-label="Закрыть" onClick={onClose}>
          <IconClose size={18} />
        </button>
      </header>
      <div className="panelview__scroll">
        <div className="profile">
          <div className="profile__avatar" style={avatarUrl ? { backgroundImage: `url("${avatarUrl}")` } : undefined}>
            {avatarUrl ? "" : initial}
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

        {taste.length > 0 && (
          <>
            <div className="recs__section">Твой вкус</div>
            <div className="taste">
              <div className="taste__bar">
                {taste.map((t) => (
                  <span key={t.key} className="taste__seg" style={{ width: `${t.pct}%`, background: t.meta.color }} title={t.meta.label} />
                ))}
              </div>
              <div className="taste__chips">
                {taste.slice(0, 4).map((t) => (
                  <span key={t.key} className="taste__chip">
                    <span className="taste__dot" style={{ background: t.meta.color }} />
                    {t.meta.label}
                    <b>{t.n}</b>
                  </span>
                ))}
              </div>
            </div>
          </>
        )}

        {favs.length > 0 ? (
          <>
            <div className="recs__section">
              Избранное
              <span className="recs__n">{favs.length}</span>
            </div>
            {favs.map((it, i) => (
              <EventRow key={it.event_id} item={it} index={i} query={query} userPos={userPos} onSelect={onSelect} />
            ))}
          </>
        ) : (
          <p className="panelview__hint">
            Отмечай события сердечком в карточке — они появятся здесь. Город определяется по твоей геолокации прямо в карте.
          </p>
        )}
      </div>
    </div>
  );
}
