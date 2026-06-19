import { useEffect, useState } from "react";

import { fetchEventsByIds, type EventItem } from "../../api/client";
import { categoryMeta } from "../../lib/categories";
import { IconClose } from "../../lib/icons";
import type { TgUser } from "../../lib/telegram";
import { safeHttpUrl } from "../../lib/url";

export function ProfilePanel({
  user,
  total,
  city,
  favIds,
  notifyDigest,
  onToggleDigest,
  onClose,
}: {
  user: TgUser | null;
  total: number;
  city: string;
  favIds: Set<string>;
  notifyDigest: boolean;
  onToggleDigest: (on: boolean) => void;
  onClose: () => void;
}) {
  const name = user ? [user.first_name, user.last_name].filter(Boolean).join(" ") || "Гость" : "Гость";
  const initial = (name[0] || "?").toUpperCase();
  const avatarUrl = safeHttpUrl(user?.photo_url);
  // Hydrate the favourites by id (not the map's loaded set) so the taste mix is accurate.
  const [favs, setFavs] = useState<EventItem[]>([]);
  const idsKey = [...favIds].sort().join(",");
  useEffect(() => {
    const ids = idsKey ? idsKey.split(",") : [];
    if (!ids.length) {
      setFavs([]);
      return;
    }
    fetchEventsByIds(ids).then(setFavs);
  }, [idsKey]);

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
        <div className="profile__hero">
          <div className="profile__stat">
            <span className="hero-num">{total}</span>
            <span className="kicker kicker--code">событий в городе</span>
          </div>
          <div className="profile__stat">
            <span className="hero-num">{favIds.size}</span>
            <span className="kicker kicker--code">в избранном</span>
          </div>
        </div>
        <div className="profile__rows">
          <div className="profile__row">
            <span>Город</span>
            <b>{city}</b>
          </div>
        </div>

        <button
          type="button"
          className={`profile__switch${notifyDigest ? " profile__switch--on" : ""}`}
          role="switch"
          aria-checked={notifyDigest}
          onClick={() => onToggleDigest(!notifyDigest)}
        >
          <span className="profile__switch-text">
            <span className="profile__switch-label">Афиша на выходные</span>
            <span className="profile__switch-sub">Раз в неделю бот пришлёт, что нового рядом и на твоих площадках</span>
          </span>
          <span className="profile__switch-track" aria-hidden="true">
            <span className="profile__switch-knob" />
          </span>
        </button>

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

        {taste.length === 0 && (
          <p className="panelview__hint">
            Отмечай события сердечком в карточке — они соберутся во вкладке «Избранное», а здесь сложится твой вкус. Город определяется по геолокации прямо в карте.
          </p>
        )}
      </div>
    </div>
  );
}
