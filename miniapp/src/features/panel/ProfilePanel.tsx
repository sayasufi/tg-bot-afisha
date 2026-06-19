import { useEffect, useMemo, useState } from "react";

import { fetchEventsByIds, type EventItem } from "../../api/client";
import { categoryMeta } from "../../lib/categories";
import { formatWhenShort } from "../../lib/datetime";
import { IconClose } from "../../lib/icons";
import type { TgUser } from "../../lib/telegram";
import { safeHttpUrl } from "../../lib/url";

export function ProfilePanel({
  user,
  total: _total,
  city,
  favIds,
  notifyReminders,
  onToggleReminders,
  notifyDigest,
  onToggleDigest,
  onSelect,
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
  onSelect: (i: EventItem) => void;
  onClose: () => void;
}) {
  const name = user ? [user.first_name, user.last_name].filter(Boolean).join(" ") || "Гость" : "Гость";
  const initial = (name[0] || "?").toUpperCase();
  const avatarUrl = safeHttpUrl(user?.photo_url);
  const handle = user?.username ? `@${user.username}` : "Telegram";
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

  // «Скоро начнётся» — your SAVED events that start within the next week, soonest first. Drives
  // both the «скоро» stat and the actionable block below. Honest (date-based); the app tracks no
  // "visits"/attendance, so we never invent that.
  const soonList = useMemo(() => {
    const now = Date.now();
    const horizon = now + 7 * 86400 * 1000;
    return favs
      .filter((f) => {
        const t = new Date(f.date_start).getTime();
        return !Number.isNaN(t) && t >= now && t <= horizon;
      })
      .sort((a, b) => new Date(a.date_start).getTime() - new Date(b.date_start).getTime());
  }, [favs]);

  // "Твой вкус" — favourite category mix, ranked.
  const taste = useMemo(() => {
    const counts = new Map<string, number>();
    for (const it of favs) counts.set(it.category, (counts.get(it.category) || 0) + 1);
    return [...counts.entries()].sort((a, b) => b[1] - a[1]).map(([key, n]) => ({ key, n, meta: categoryMeta(key) }));
  }, [favs]);

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
            <div className="profile__handle">
              {handle} · {city}
            </div>
          </div>
        </div>

        {/* All three stats are about YOU — saved · soon · taste breadth. No standalone city/DB
            number (that read as «Я · Я · Сервер»); the city lives in the identity line above. */}
        <div className="profile__hero profile__hero--3">
          <div className="profile__stat">
            <span className="hero-num">{favIds.size}</span>
            <span className="kicker kicker--code">сохранено</span>
          </div>
          <div className="profile__stat">
            <span className="hero-num">{soonList.length}</span>
            <span className="kicker kicker--code">скоро</span>
          </div>
          <div className="profile__stat">
            <span className="hero-num">{taste.length}</span>
            <span className="kicker kicker--code">категории</span>
          </div>
        </div>

        {/* «Твой вкус» — the cultural passport as editorial genre tags (NOT a multi-colour chart:
            that broke the acid+cinnabar system). The top genre wears the one cinnabar accent. */}
        <div className="recs__section recs__section--you">Твой вкус</div>
        {taste.length > 0 ? (
          <div className="taste">
            {taste.slice(0, 6).map((t, i) => (
              <span key={t.key} className={`tastetag${i === 0 ? " tastetag--top" : ""}`}>
                {t.meta.label.toLowerCase()}
                <b>{t.n}</b>
              </span>
            ))}
          </div>
        ) : (
          <div className="profile__empty">
            <span className="profile__empty-title">пока пусто</span>
            <span className="profile__empty-text">
              Сохраняй события сердечком — и здесь сложится твой культурный профиль: любимые жанры, площадки, ритм города.
            </span>
          </div>
        )}

        {/* «Скоро начнётся» — your soonest saved events, tappable. Ends the passport with content +
            a reason to act, not with settings. */}
        {soonList.length > 0 && (
          <>
            <div className="recs__section">Скоро начнётся</div>
            <div className="profile__soon">
              {soonList.slice(0, 3).map((ev) => (
                <button key={ev.event_id} type="button" className="profile__soonrow" onClick={() => onSelect(ev)}>
                  <span className="profile__soontitle">{ev.title}</span>
                  <span className="profile__soonwhen">{formatWhenShort(ev.date_start, ev.date_end)}</span>
                </button>
              ))}
            </div>
          </>
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
