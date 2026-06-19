import { useEffect, useMemo, useState } from "react";

import { fetchEventsByIds, type City, type EventItem } from "../../api/client";
import { viewedCount } from "../../lib/affinity";
import { categoryMeta } from "../../lib/categories";
import { CategoryIcon, IconClose } from "../../lib/icons";
import type { TgUser } from "../../lib/telegram";
import { safeHttpUrl } from "../../lib/url";

export function ProfilePanel({
  user,
  city,
  cities,
  onSelectCity,
  favIds,
  goingCount,
  notifyReminders,
  onToggleReminders,
  notifyDigest,
  onToggleDigest,
  onOpenFavorites,
  onClose,
}: {
  user: TgUser | null;
  city: string;
  cities: City[];
  onSelectCity: (slug: string) => void;
  favIds: Set<string>;
  goingCount: number;
  notifyReminders: boolean;
  onToggleReminders: (on: boolean) => void;
  notifyDigest: boolean;
  onToggleDigest: (on: boolean) => void;
  onOpenFavorites: () => void;
  onClose: () => void;
}) {
  const [cityOpen, setCityOpen] = useState(false);
  const name = user ? [user.first_name, user.last_name].filter(Boolean).join(" ") || "Гость" : "Гость";
  const initial = (name[0] || "?").toUpperCase();
  const avatarUrl = safeHttpUrl(user?.photo_url);
  const handle = user?.username ? `@${user.username}` : "Telegram";
  // «Просмотрено» — unique events opened on this device (a real behavioural metric, not derivable
  // from the Избранное list). Read once on open.
  const [viewed] = useState(() => viewedCount());

  // Hydrate the favourites by id so the taste card shows their posters + genres.
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

  // Ranked favourite genres (for the card caption).
  const taste = useMemo(() => {
    const counts = new Map<string, number>();
    for (const it of favs) counts.set(it.category, (counts.get(it.category) || 0) + 1);
    return [...counts.entries()].sort((a, b) => b[1] - a[1]).map(([key, n]) => ({ key, n, meta: categoryMeta(key) }));
  }, [favs]);
  const hasTaste = favs.length > 0;

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
            <div className="profile__handle">{handle}</div>
          </div>
        </div>

        {/* Real behavioural stats — a viewed → saved → going funnel. Each is something you DID, not
            a breakdown you could already read off the Избранное list. */}
        <div className="profile__hero profile__hero--3">
          <div className="profile__stat">
            <span className="hero-num">{viewed}</span>
            <span className="profile__statlabel">просмотрено</span>
          </div>
          <div className="profile__stat">
            <span className="hero-num">{favIds.size}</span>
            <span className="profile__statlabel">сохранено</span>
          </div>
          <div className="profile__stat">
            <span className="hero-num">{goingCount}</span>
            <span className="profile__statlabel">иду</span>
          </div>
        </div>

        {/* City — selectable. Only Москва is active today; the picker is ready for more. */}
        <div className="profile__cityrow">
          <button type="button" className="profile__city" aria-expanded={cityOpen} onClick={() => setCityOpen((o) => !o)}>
            <span className="profile__city-name">{city}</span>
            <span className={`profile__city-chev${cityOpen ? " profile__city-chev--open" : ""}`} aria-hidden="true">›</span>
          </button>
          {cityOpen && (
            <div className="profile__city-list">
              {cities.map((c) => (
                <button
                  key={c.slug}
                  type="button"
                  className={`profile__city-opt${c.name === city ? " profile__city-opt--on" : ""}`}
                  onClick={() => {
                    onSelectCity(c.slug);
                    setCityOpen(false);
                  }}
                >
                  <span>{c.name}</span>
                  {c.name === city && <span aria-hidden="true">✓</span>}
                </button>
              ))}
              {cities.length <= 1 && <span className="profile__city-soon">другие города — скоро</span>}
            </div>
          )}
        </div>

        {/* «Твой вкус» — a card whose visualisation IS a contact-sheet of your saved-event posters
            (your taste as images). Tap → Избранное. Empty → placeholder grid + a nudge. */}
        <button type="button" className="tastecard" aria-label="Твой вкус — открыть избранное" onClick={onOpenFavorites}>
          <span className="tastecard__head">
            <span className="tastecard__title">Твой вкус</span>
            <span className="tastecard__chev" aria-hidden="true">→</span>
          </span>
          {hasTaste ? (
            <>
              <span className="tastecard__grid">
                {favs.slice(0, 6).map((f) => {
                  const img = safeHttpUrl(f.primary_image_url);
                  return (
                    <span key={f.event_id} className="tastecard__cell">
                      {img ? (
                        <img className="tastecard__img" src={img} alt="" loading="lazy" decoding="async" />
                      ) : (
                        <span className="tastecard__glyph">
                          <CategoryIcon cat={f.category} size={18} />
                        </span>
                      )}
                    </span>
                  );
                })}
              </span>
              <span className="tastecard__cap">{taste.slice(0, 4).map((t) => t.meta.label.toLowerCase()).join(" · ")}</span>
            </>
          ) : (
            <>
              <span className="tastecard__nudge">Пока ничего нет. Сохрани несколько событий — и здесь сложится твой культурный профиль.</span>
              <span className="tastecard__grid">
                {Array.from({ length: 6 }).map((_, i) => (
                  <span key={i} className="tastecard__cell tastecard__cell--empty" />
                ))}
              </span>
            </>
          )}
        </button>

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
