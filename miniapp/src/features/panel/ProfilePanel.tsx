import { useEffect, useState } from "react";

import { fetchEventsByIds, type City, type EventItem } from "../../api/client";
import { viewedCount } from "../../lib/affinity";
import { IconClose } from "../../lib/icons";
import type { ThemeName, TgUser } from "../../lib/telegram";
import { safeHttpUrl } from "../../lib/url";
import { TasteCard } from "./TasteCard";

export function ProfilePanel({
  user,
  city,
  cities,
  onSelectCity,
  favIds,
  notifyReminders,
  onToggleReminders,
  notifyDigest,
  onToggleDigest,
  friendsPrivate,
  onToggleFriendsPrivate,
  theme = "light",
  onToggleTheme,
  onOpenFavorites,
  onClose,
}: {
  user: TgUser | null;
  city: string;
  cities: City[];
  onSelectCity: (slug: string) => void;
  favIds: Set<string>;
  notifyReminders: boolean;
  onToggleReminders: (on: boolean) => void;
  notifyDigest: boolean;
  onToggleDigest: (on: boolean) => void;
  friendsPrivate: boolean;
  onToggleFriendsPrivate: (on: boolean) => void;
  theme?: ThemeName;
  onToggleTheme?: () => void;
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

        {/* Real behavioural stats — a viewed → saved funnel. Each is something you DID, not a
            breakdown you could already read off the Избранное list. */}
        <div className="profile__hero profile__hero--2">
          <div className="profile__stat">
            <span className="hero-num">{viewed}</span>
            <span className="profile__statlabel">просмотрено</span>
          </div>
          <button type="button" className="profile__stat profile__stat--tap" onClick={onOpenFavorites}>
            <span className="hero-num">{favIds.size}</span>
            <span className="profile__statlabel">сохранено</span>
          </button>
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

        {/* «Твой вкус» — a constellation of your saved-event genres (the «кружочки»); tap → Избранное. */}
        <TasteCard events={favs} title="Твой вкус" onTap={onOpenFavorites} />

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
            <span className="profile__switch-sub">Бот напомнит перед началом событий из избранного. Выключи, чтобы приглушить все разом</span>
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

        <div className="recs__section">Приватность</div>
        <button
          type="button"
          className={`profile__switch${friendsPrivate ? " profile__switch--on" : ""}`}
          role="switch"
          aria-checked={friendsPrivate}
          onClick={() => onToggleFriendsPrivate(!friendsPrivate)}
        >
          <span className="profile__switch-text">
            <span className="profile__switch-label">Скрыть от друзей</span>
            <span className="profile__switch-sub">Друзья не увидят, что ты сохраняешь — ни в профиле, ни на карте</span>
          </span>
          <span className="profile__switch-track" aria-hidden="true">
            <span className="profile__switch-knob" />
          </span>
        </button>

        <div className="recs__section">Оформление</div>
        <button
          type="button"
          className={`profile__switch${theme === "dark" ? " profile__switch--on" : ""}`}
          role="switch"
          aria-checked={theme === "dark"}
          onClick={() => onToggleTheme?.()}
        >
          <span className="profile__switch-text">
            <span className="profile__switch-label">После заката</span>
            <span className="profile__switch-sub">Тёмная тема — тёплые чернила вместо белого куба</span>
          </span>
          <span className="profile__switch-track" aria-hidden="true">
            <span className="profile__switch-knob" />
          </span>
        </button>
      </div>
    </div>
  );
}
