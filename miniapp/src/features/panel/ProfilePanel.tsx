import { useEffect, useMemo, useState } from "react";

import { fetchEventsByIds, type City, type EventItem } from "../../api/client";
import { viewedCount } from "../../lib/affinity";
import { categoryMeta } from "../../lib/categories";
import { CategoryIcon, IconClose } from "../../lib/icons";
import type { TgUser } from "../../lib/telegram";
import { safeHttpUrl } from "../../lib/url";

// Irregular «клякса» radii (one per blob, by index) — uneven organic shapes, not perfect circles.
const BLOB_SHAPES = [
  "42% 58% 68% 32% / 46% 44% 56% 54%",
  "63% 37% 41% 59% / 50% 56% 44% 50%",
  "38% 62% 60% 40% / 42% 47% 53% 58%",
  "55% 45% 33% 67% / 58% 40% 60% 42%",
  "66% 34% 52% 48% / 40% 60% 40% 60%",
  "48% 52% 59% 41% / 54% 57% 43% 46%",
];
const fract = (x: number) => x - Math.floor(x);
// Deterministic organic cluster position (% of the box) for blob i of n: biggest centred, the
// rest placed around it at even angles + a stable jitter so they overlap into a chaotic клякса-cluster.
function blobPos(i: number, n: number): { x: number; y: number } {
  if (i === 0) return { x: 50, y: 47 };
  const around = Math.max(1, n - 1);
  const angle = ((i - 1) / around) * Math.PI * 2 - Math.PI / 2 + (fract(Math.sin(i * 12.9) * 4137) - 0.5) * 0.8;
  const jr = fract(Math.sin(i * 78.2) * 2719);
  return { x: 50 + Math.cos(angle) * (23 + jr * 7), y: 47 + Math.sin(angle) * (27 + jr * 8) };
}

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
              <span className="tastecard__blobs">
                {taste.slice(0, 6).map((t, i, arr) => {
                  const d = 48 + Math.round((t.n / arr[0].n) * 44); // diameter ∝ genre share
                  const pos = blobPos(i, arr.length);
                  return (
                    <span
                      key={t.key}
                      className="blob"
                      style={{
                        width: `${d}px`,
                        height: `${d}px`,
                        left: `${pos.x}%`,
                        top: `${pos.y}%`,
                        background: t.meta.color,
                        borderRadius: BLOB_SHAPES[i % BLOB_SHAPES.length],
                        zIndex: i + 1,
                      }}
                    >
                      <CategoryIcon cat={t.key} size={Math.round(d * 0.4)} />
                    </span>
                  );
                })}
              </span>
              <span className="tastecard__cap">{taste.slice(0, 4).map((t) => t.meta.label.toLowerCase()).join(" · ")}</span>
            </>
          ) : (
            <>
              <span className="tastecard__nudge">Пока ничего нет. Сохрани несколько событий — и здесь сложится твой культурный профиль.</span>
              <span className="tastecard__blobs">
                {[84, 58, 66, 48, 54].map((d, i) => {
                  const pos = blobPos(i, 5);
                  return (
                    <span
                      key={i}
                      className="blob blob--empty"
                      style={{ width: `${d}px`, height: `${d}px`, left: `${pos.x}%`, top: `${pos.y}%`, borderRadius: BLOB_SHAPES[i % BLOB_SHAPES.length] }}
                    />
                  );
                })}
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
