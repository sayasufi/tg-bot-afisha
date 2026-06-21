import { useEffect, useMemo, useState } from "react";

import { fetchEventsByIds, type City, type EventItem } from "../../api/client";
import { manageFriends, type Friend, type FriendsState } from "../../api/users";
import { viewedCount } from "../../lib/affinity";
import { FriendDisclosure } from "./FriendDisclosure";
import { categoryMeta } from "../../lib/categories";
import { CategoryIcon, IconClose } from "../../lib/icons";
import type { ThemeName, TgUser } from "../../lib/telegram";
import { safeHttpUrl } from "../../lib/url";

// Pixel offset from the box centre for circle i of n, by share rank — a tight OVERLAPPING RING with
// a touch of spiral: the dominant leads up-left, each circle overlaps its neighbours, the radius
// grows a hair per step (the spiral). PX (not %) so it never stretches/clips on a wide box.
function clusterPos(i: number, n: number): { dx: number; dy: number } {
  const step = (2 * Math.PI) / Math.max(n, 3);
  const angle = -2.2 + i * step;
  const p = 48 + i * 4; // ring radius px, slight growth = spiral
  return { dx: Math.cos(angle) * p * 1.1, dy: Math.sin(angle) * p };
}

const eventsBasis = (n: number) => `основано на ${n} ${n === 1 ? "сохранённом событии" : "сохранённых событиях"}`;

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
  // Friends + incoming requests — fetched once on open; managed in place.
  const [friends, setFriends] = useState<Friend[]>([]);
  const [requests, setRequests] = useState<Friend[]>([]);
  const [disclose, setDisclose] = useState(false);
  const apply = (s: FriendsState | null) => {
    if (!s) return;
    setFriends(s.friends);
    setRequests(s.requests);
  };
  useEffect(() => {
    let alive = true;
    manageFriends().then((s) => {
      if (alive) apply(s);
    });
    return () => {
      alive = false;
    };
  }, []);
  const removeFriend = (id: number) => {
    setFriends((fs) => fs.filter((f) => f.id !== id)); // optimistic
    void manageFriends("remove", id).then(apply);
  };
  const acceptRequest = (id: number) => {
    setRequests((rs) => rs.filter((r) => r.id !== id)); // optimistic
    void manageFriends("accept", id).then((s) => {
      apply(s);
      // First friendship → show the one-time visibility disclosure (favourites become visible).
      if (s?.firstFriend) {
        try {
          if (localStorage.getItem("okrest_friend_disclosed") !== "1") {
            localStorage.setItem("okrest_friend_disclosed", "1");
            setDisclose(true);
          }
        } catch {
          /* ignore */
        }
      }
    });
  };
  const declineRequest = (id: number) => {
    setRequests((rs) => rs.filter((r) => r.id !== id)); // optimistic
    void manageFriends("decline", id).then(apply);
  };
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

        {/* «Твой вкус» — a card whose visualisation IS a contact-sheet of your saved-event posters
            (your taste as images). Tap → Избранное. Empty → placeholder grid + a nudge. */}
        <button type="button" className="tastecard" aria-label="Твой вкус — открыть избранное" onClick={onOpenFavorites}>
          <span className="tastecard__head">
            <span className="tastecard__title">Твой вкус</span>
            <span className="tastecard__chev" aria-hidden="true">→</span>
          </span>
          {hasTaste ? (
            <>
              <span className="tastecard__cluster">
                {taste.slice(0, 6).map((t, i, arr) => {
                  const d = 64 + Math.round((t.n / arr[0].n) * 28); // 64..92px, by genre share
                  const pos = clusterPos(i, arr.length);
                  const top = i === 0;
                  return (
                    <span
                      key={t.key}
                      className={`tcircle${top ? " tcircle--top" : ""}`}
                      style={{ width: `${d}px`, height: `${d}px`, left: `calc(50% + ${pos.dx}px)`, top: `calc(50% + ${pos.dy}px)`, zIndex: top ? 20 : i + 1 }}
                    >
                      <CategoryIcon cat={t.key} size={Math.round(d * 0.28)} />
                      <span className="tcircle__label">{t.meta.label.toLowerCase()}</span>
                      <span className="tcircle__n">{t.n}</span>
                    </span>
                  );
                })}
                {/* Accent dots fill the gaps — the «constellation» finish. */}
                <span className="tdot tdot--acid" style={{ left: "84%", top: "18%" }} />
                <span className="tdot" style={{ left: "14%", top: "26%" }} />
                <span className="tdot tdot--acid" style={{ left: "76%", top: "84%" }} />
                <span className="tdot" style={{ left: "26%", top: "86%" }} />
              </span>
              <span className="tastecard__basis">{eventsBasis(favs.length)}</span>
            </>
          ) : (
            <>
              <span className="tastecard__nudge">Пока ничего нет. Сохрани несколько событий — и здесь сложится твой культурный профиль.</span>
              <span className="tastecard__cluster">
                {[86, 70, 74, 64, 68].map((d, i) => {
                  const pos = clusterPos(i, 5);
                  return (
                    <span key={i} className="tcircle tcircle--empty" style={{ width: `${d}px`, height: `${d}px`, left: `calc(50% + ${pos.dx}px)`, top: `calc(50% + ${pos.dy}px)` }} />
                  );
                })}
              </span>
            </>
          )}
        </button>

        {/* Incoming requests — people who accepted your «Пойдём?». You decide (a pending edge shows
            nothing to either side until you accept). */}
        {requests.length > 0 && (
          <>
            <div className="recs__section">Заявки в друзья</div>
            <div className="profile__friends">
              {requests.map((f) => {
                const rav = safeHttpUrl(f.photo_url);
                const ri = (f.name || "?").slice(0, 1).toUpperCase();
                return (
                  <div className="profile__friend" key={f.id}>
                    <span
                      className="profile__friend-av"
                      style={rav ? { backgroundImage: `url("${rav}")` } : undefined}
                    >
                      {rav ? "" : ri}
                    </span>
                    <span className="profile__friend-id">
                      <span className="profile__friend-name">{f.name || "Друг"}</span>
                      {f.username && <span className="profile__friend-handle">@{f.username}</span>}
                    </span>
                    <span className="profile__req-actions">
                      <button type="button" className="profile__req-accept" onClick={() => acceptRequest(f.id)}>
                        принять
                      </button>
                      <button
                        type="button"
                        className="profile__friend-x"
                        aria-label={`Отклонить ${f.name || "заявку"}`}
                        onClick={() => declineRequest(f.id)}
                      >
                        ×
                      </button>
                    </span>
                  </div>
                );
              })}
            </div>
          </>
        )}

        {/* Друзья — confirmed friendships. The privacy controls live right here. */}
        <div className="recs__section">Друзья</div>
        {friends.length > 0 ? (
          <div className="profile__friends">
            {friends.map((f) => {
              const fav = safeHttpUrl(f.photo_url);
              const fi = (f.name || "?").slice(0, 1).toUpperCase();
              return (
                <div className="profile__friend" key={f.id}>
                  <span
                    className="profile__friend-av"
                    style={fav ? { backgroundImage: `url("${fav}")` } : undefined}
                  >
                    {fav ? "" : fi}
                  </span>
                  <span className="profile__friend-id">
                    <span className="profile__friend-name">{f.name || "Друг"}</span>
                    {f.username && <span className="profile__friend-handle">@{f.username}</span>}
                  </span>
                  <button
                    type="button"
                    className="profile__friend-x"
                    aria-label={`Убрать ${f.name || "друга"} из друзей`}
                    onClick={() => removeFriend(f.id)}
                  >
                    ×
                  </button>
                </div>
              );
            })}
          </div>
        ) : (
          <p className="profile__friends-empty">
            Поделись событием через «Пойдём?» — кто примет, попадёт в заявки, а после подтверждения вы будете
            видеть, что друг у друга в избранном.
          </p>
        )}
        <button
          type="button"
          className={`profile__switch${friendsPrivate ? " profile__switch--on" : ""}`}
          role="switch"
          aria-checked={friendsPrivate}
          onClick={() => onToggleFriendsPrivate(!friendsPrivate)}
        >
          <span className="profile__switch-text">
            <span className="profile__switch-label">Скрыть от друзей</span>
            <span className="profile__switch-sub">Друзья не увидят, что ты сохраняешь. Отдельное событие можно скрыть в его карточке</span>
          </span>
          <span className="profile__switch-track" aria-hidden="true">
            <span className="profile__switch-knob" />
          </span>
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
      {disclose && <FriendDisclosure onClose={() => setDisclose(false)} />}
    </div>
  );
}
