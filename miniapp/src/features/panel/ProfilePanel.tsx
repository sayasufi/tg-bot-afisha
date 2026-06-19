import { useEffect, useMemo, useState } from "react";

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
  notifyReminders,
  onToggleReminders,
  notifyDigest,
  onToggleDigest,
  onClose,
}: {
  user: TgUser | null;
  total: number;
  city: string;
  favIds: Set<string>;
  notifyReminders: boolean;
  onToggleReminders: (on: boolean) => void;
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

  // «Скоро» — how many of your SAVED events start within the next week. An actionable, honest
  // nudge to come back (the app tracks no "visits"/attendance, so we never invent that metric).
  const soonCount = useMemo(() => {
    const now = Date.now();
    const horizon = now + 7 * 86400 * 1000;
    return favs.filter((f) => {
      const t = new Date(f.date_start).getTime();
      return !Number.isNaN(t) && t >= now && t <= horizon;
    }).length;
  }, [favs]);

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
        <h2>профиль</h2>
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

        {/* Personal stats lead (saved · soon); the city + its count are folded in as the third cell,
            so there's no standalone vanity "7269 в городе" and no separate «Город» row. */}
        <div className="profile__hero profile__hero--3">
          <div className="profile__stat">
            <span className="hero-num">{favIds.size}</span>
            <span className="kicker kicker--code">сохранено</span>
          </div>
          <div className="profile__stat">
            <span className="hero-num">{soonCount}</span>
            <span className="kicker kicker--code">скоро</span>
          </div>
          <div className="profile__stat">
            <span className="hero-num">{total}</span>
            <span className="kicker kicker--code">{city}</span>
          </div>
        </div>

        {/* «Твой вкус» — the cultural-passport block, ALWAYS shown (mix or an inviting empty state)
            and ABOVE the settings, so the profile reads as "who you are", not just toggles. */}
        <div className="recs__section recs__section--you">Твой вкус</div>
        {taste.length > 0 ? (
          <div className="taste">
            <div className="taste__bar">
              {taste.map((t) => (
                <span key={t.key} className="taste__seg" style={{ width: `${t.pct}%`, background: t.meta.color }} title={t.meta.label} />
              ))}
            </div>
            <div className="taste__chips">
              {taste.slice(0, 5).map((t) => (
                <span key={t.key} className="taste__chip">
                  <span className="taste__dot" style={{ background: t.meta.color }} />
                  {t.meta.label}
                  <b>{t.n}</b>
                </span>
              ))}
            </div>
          </div>
        ) : (
          <div className="profile__empty">
            <span className="profile__empty-title">пока пусто</span>
            <span className="profile__empty-text">
              Сохраняй события сердечком — и здесь сложится твой культурный профиль: любимые жанры, площадки, ритм города.
            </span>
          </div>
        )}

        {/* Settings, grouped under their own header below the passport. */}
        <div className="recs__section">Уведомления</div>
        <button
          type="button"
          className={`profile__switch${notifyReminders ? " profile__switch--on" : ""}`}
          role="switch"
          aria-checked={notifyReminders}
          onClick={() => onToggleReminders(!notifyReminders)}
        >
          <span className="profile__switch-text">
            <span className="profile__switch-label">Напоминания</span>
            <span className="profile__switch-sub">Бот пишет перед началом событий, где ты нажал колокол. Выключи, чтобы приглушить все разом</span>
          </span>
          <span className="profile__switch-track" aria-hidden="true">
            <span className="profile__switch-knob" />
          </span>
        </button>

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
      </div>
    </div>
  );
}
