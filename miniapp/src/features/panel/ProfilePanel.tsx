import { useEffect, useState } from "react";

import { fetchEventsByIds, type City, type EventItem } from "../../api/client";
import { viewedCount } from "../../lib/affinity";
import { IconClose } from "../../lib/icons";
import { MANAGER_LINK, openTelegramLink, type ThemeName, type TgUser } from "../../lib/telegram";
import { safeHttpUrl } from "../../lib/url";
import { authLinkCode, authMe, authSetCredentials, getWebEmail, getWebToken, logoutWeb } from "../../lib/webAuth";
import { WebAccountPanel } from "../auth/WebAccountPanel";
import { showToast } from "../../lib/toast";
import { SuggestChannelModal } from "./SuggestChannelModal";
import { SuggestEventModal } from "./SuggestEventModal";
import { TasteCard } from "./TasteCard";

export function ProfilePanel({
  webMode = false,
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
  webMode?: boolean; // браузер без Telegram: секция веб-аккаунта, TG-специфика скрыта/приглушена
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
  const [suggestOpen, setSuggestOpen] = useState(false);
  const [channelOpen, setChannelOpen] = useState(false);
  // Веб-аккаунт (браузер): вход-оверлей + связка с Telegram. authMe даёт linked-статус.
  const [webAuthOpen, setWebAuthOpen] = useState(false);
  const [webLinked, setWebLinked] = useState<boolean | null>(null);
  const webAuthed = webMode && !!getWebToken();
  useEffect(() => {
    if (!webAuthed) return;
    void authMe().then((m) => {
      if (m) setWebLinked(m.telegram_linked);
    });
  }, [webAuthed]);
  // Уведомления шлёт БОТ: чисто-веб аккаунту (без связки) тумблеры честно приглушаем.
  const notifyLocked = webMode && webAuthed && webLinked === false;
  const linkTg = async () => {
    const url = await authLinkCode();
    if (url) window.open(url, "_blank");
    else showToast("Не получилось — попробуй позже", { tone: "muted" });
  };
  // «Вход на сайте»: email+пароль на этот же TG-аккаунт → логин на okrestmap.ru/в приложениях
  // ведёт в тот же аккаунт (избранное/настройки общие).
  const [webCredsOpen, setWebCredsOpen] = useState(false);
  const [webEmail, setWebEmail] = useState("");
  const [webPassword, setWebPassword] = useState("");
  const [webBusy, setWebBusy] = useState(false);
  const saveWebCreds = async () => {
    if (!webEmail.trim() || webPassword.length < 8) {
      showToast(webPassword.length < 8 ? "Пароль — минимум 8 символов" : "Укажи email", { tone: "muted" });
      return;
    }
    setWebBusy(true);
    const r = await authSetCredentials(webEmail, webPassword);
    setWebBusy(false);
    if (r.ok) {
      showToast("Готово — входи на сайте с этим email", { tone: "good" });
      setWebCredsOpen(false);
      setWebPassword("");
    } else {
      showToast(r.data.detail || "Не получилось — попробуй позже", { tone: "muted" });
    }
  };
  // Cities A→Z (Cyrillic-aware) so the picker stays scannable as it grows past a dozen.
  const sortedCities = [...cities].sort((a, b) => a.name.localeCompare(b.name, "ru"));
  const currentCitySlug = cities.find((c) => c.name === city)?.slug ?? cities[0]?.slug ?? "";
  const webAccEmail = webMode ? getWebEmail() : null;
  const name = webMode
    ? (webAccEmail ?? "Гость")
    : user ? [user.first_name, user.last_name].filter(Boolean).join(" ") || "Гость" : "Гость";
  const initial = (name[0] || "?").toUpperCase();
  const avatarUrl = safeHttpUrl(user?.photo_url);
  const handle = webMode
    ? (webAuthed ? "веб-аккаунт" : "не выполнен вход")
    : user?.username ? `@${user.username}` : "Telegram";
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
    <>
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
              {sortedCities.map((c) => (
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
          disabled={notifyLocked}
          style={notifyLocked ? { opacity: 0.5 } : undefined}
          onClick={() => !notifyLocked && onToggleReminders(!notifyReminders)}
        >
          <span className="profile__switch-text">
            <span className="profile__switch-label">Напоминания</span>
            <span className="profile__switch-sub">
              {notifyLocked
                ? "Придут в Telegram — свяжи аккаунт выше"
                : "Бот напомнит перед началом событий из избранного. Выключи, чтобы приглушить все разом"}
            </span>
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
          disabled={notifyLocked}
          style={notifyLocked ? { opacity: 0.5 } : undefined}
          onClick={() => !notifyLocked && onToggleDigest(!notifyDigest)}
        >
          <span className="profile__switch-text">
            <span className="profile__switch-label">Афиша на выходные</span>
            <span className="profile__switch-sub">
              {notifyLocked
                ? "Придёт в Telegram — свяжи аккаунт выше"
                : "Раз в неделю бот пришлёт, что нового рядом и на твоих площадках"}
            </span>
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

        <div className="recs__section">Аккаунт</div>
        {webMode && !webAuthed && (
          <button type="button" className="profile__switch" onClick={() => setWebAuthOpen(true)}>
            <span className="profile__switch-text">
              <span className="profile__switch-label">Войти или создать аккаунт</span>
              <span className="profile__switch-sub">Избранное и настройки сохранятся за тобой</span>
            </span>
            <span aria-hidden="true" style={{ opacity: 0.6 }}>→</span>
          </button>
        )}
        {webMode && webAuthed && (
          <>
            {webLinked === false && (
              <button type="button" className="profile__switch" onClick={() => void linkTg()}>
                <span className="profile__switch-text">
                  <span className="profile__switch-label">Связать Telegram</span>
                  <span className="profile__switch-sub">Избранное станет общим, а бот будет напоминать о событиях</span>
                </span>
                <span aria-hidden="true" style={{ opacity: 0.6 }}>→</span>
              </button>
            )}
            <button
              type="button"
              className="profile__switch"
              onClick={() => {
                logoutWeb();
                window.location.reload();
              }}
            >
              <span className="profile__switch-text">
                <span className="profile__switch-label">Выйти</span>
                <span className="profile__switch-sub">{webAccEmail ?? "веб-аккаунт"}</span>
              </span>
              <span aria-hidden="true" style={{ opacity: 0.6 }}>×</span>
            </button>
          </>
        )}
        {!webMode && (<>
        <button type="button" className="profile__switch" onClick={() => setWebCredsOpen((v) => !v)}>
          <span className="profile__switch-text">
            <span className="profile__switch-label">Вход на сайте</span>
            <span className="profile__switch-sub">
              Задай email и пароль — и этот же аккаунт откроется на okrestmap.ru и в будущих приложениях
            </span>
          </span>
          <span aria-hidden="true" style={{ opacity: 0.6 }}>{webCredsOpen ? "×" : "→"}</span>
        </button>
        {webCredsOpen && (
          <div style={{ display: "grid", gap: 8, padding: "4px 2px 10px" }}>
            <input
              type="email"
              placeholder="email"
              autoComplete="email"
              value={webEmail}
              onChange={(e) => setWebEmail(e.target.value)}
              style={{ height: 42, padding: "0 12px", background: "var(--plinth)", color: "var(--ink)",
                       border: 0, boxShadow: "inset 0 0 0 1px var(--ink)", fontSize: 14 }}
            />
            <input
              type="password"
              placeholder="пароль (мин. 8 символов)"
              autoComplete="new-password"
              value={webPassword}
              onChange={(e) => setWebPassword(e.target.value)}
              style={{ height: 42, padding: "0 12px", background: "var(--plinth)", color: "var(--ink)",
                       border: 0, boxShadow: "inset 0 0 0 1px var(--ink)", fontSize: 14 }}
            />
            <button
              type="button"
              className="btn btn--primary"
              disabled={webBusy}
              onClick={() => void saveWebCreds()}
              style={{ height: 42 }}
            >
              {webBusy ? "…" : "Сохранить"}
            </button>
          </div>
        )}
        </>)}

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

        {/* Community contribution — propose an event that isn't on the map yet (admin-moderated). */}
        <div className="recs__section">Добавить</div>
        <button
          type="button"
          className="profile__switch profile__switch--link"
          onClick={() => setSuggestOpen(true)}
        >
          <span className="profile__switch-text">
            <span className="profile__switch-label">Предложить событие</span>
            <span className="profile__switch-sub">Знаешь событие, которого нет на карте? Добавим после проверки</span>
          </span>
          <span className="profile__switch-chev" aria-hidden="true">›</span>
        </button>
        <button
          type="button"
          className="profile__switch profile__switch--link"
          onClick={() => setChannelOpen(true)}
        >
          <span className="profile__switch-text">
            <span className="profile__switch-label">Добавить свой канал</span>
            <span className="profile__switch-sub">Ведёшь TG-канал площадки? Будем собирать афишу оттуда</span>
          </span>
          <span className="profile__switch-chev" aria-hidden="true">›</span>
        </button>

        {/* One human contact for anything — questions, ideas, "something's off". Opens the manager
            DM inside Telegram (openTelegramLink), never the in-app browser. */}
        <div className="recs__section">Помощь</div>
        <button
          type="button"
          className="profile__switch profile__switch--link"
          onClick={() => openTelegramLink(MANAGER_LINK)}
        >
          <span className="profile__switch-text">
            <span className="profile__switch-label">Написать менеджеру</span>
            <span className="profile__switch-sub">Вопросы, идеи или что-то не так — ответим в личке</span>
          </span>
          <span className="profile__switch-chev" aria-hidden="true">›</span>
        </button>
      </div>
    </div>
    {suggestOpen && (
      <SuggestEventModal open onClose={() => setSuggestOpen(false)} cities={sortedCities} defaultCity={currentCitySlug} />
    )}
    {channelOpen && (
      <SuggestChannelModal open onClose={() => setChannelOpen(false)} cities={sortedCities} defaultCity={currentCitySlug} />
    )}
    {webAuthOpen && <WebAccountPanel onClose={() => setWebAuthOpen(false)} />}
    </>
  );
}
