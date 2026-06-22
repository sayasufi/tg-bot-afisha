import { useEffect, useState } from "react";

import { fetchEventsByIds, type EventItem } from "../../api/client";
import { fetchFriendProfile, type Friend } from "../../api/users";
import type { LatLon } from "../../lib/distance";
import { IconClose } from "../../lib/icons";
import { safeHttpUrl } from "../../lib/url";
import { CatalogFeed } from "./CatalogFeed";
import { TasteCard } from "./TasteCard";

// A friend's profile — what they've saved. Opened from the Friends list. Server-gated to mutual
// friends; respects the friend's privacy (a globally-private friend shows no saves, hidden items are
// already filtered out server-side). «Вы оба сохранили N» = the overlap with your own favourites.
export function FriendProfile({
  friend,
  myFavIds,
  userPos,
  onSelect,
  onClose,
}: {
  friend: Friend;
  myFavIds: Set<string>;
  userPos?: LatLon | null;
  onSelect: (i: EventItem) => void;
  onClose: () => void;
}) {
  const [events, setEvents] = useState<EventItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [isPrivate, setIsPrivate] = useState(false);

  useEffect(() => {
    let alive = true;
    setLoading(true);
    setEvents([]);
    setIsPrivate(false);
    fetchFriendProfile(friend.id).then((p) => {
      if (!alive) return;
      if (!p) {
        setLoading(false);
        return;
      }
      setIsPrivate(p.private);
      if (p.favorite_ids.length) {
        fetchEventsByIds(p.favorite_ids).then((evs) => {
          if (alive) {
            setEvents(evs);
            setLoading(false);
          }
        });
      } else {
        setLoading(false);
      }
    });
    return () => {
      alive = false;
    };
  }, [friend.id]);

  const both = events.reduce((n, e) => (myFavIds.has(e.event_id) ? n + 1 : n), 0);
  const av = safeHttpUrl(friend.photo_url);
  const initial = (friend.name || "?").slice(0, 1).toUpperCase();

  return (
    <div className="panelview">
      <header className="panelview__head">
        <h2>{(friend.name || "друг").toLowerCase()}</h2>
        <button type="button" className="panelview__close" aria-label="Закрыть" onClick={onClose}>
          <IconClose size={18} />
        </button>
      </header>
      <div className="panelview__scroll">
        <div className="profile">
          <div className="profile__avatar" style={av ? { backgroundImage: `url("${av}")` } : undefined}>
            {av ? "" : initial}
          </div>
          <div className="profile__id">
            <div className="profile__name">{friend.name || "Друг"}</div>
            <div className="profile__handle">{friend.username ? `@${friend.username}` : "в друзьях"}</div>
          </div>
        </div>

        {events.length > 0 && (
          <>
            {/* Same stat hero as your own profile — «просмотрено» is device-local (no friend equivalent),
                so it's THEIR saves + your overlap. */}
            <div className="profile__hero profile__hero--2">
              <div className="profile__stat">
                <span className="hero-num">{events.length}</span>
                <span className="profile__statlabel">сохранено</span>
              </div>
              <div className="profile__stat">
                <span className="hero-num">{both}</span>
                <span className="profile__statlabel">совпало</span>
              </div>
            </div>
            {/* The same «кружочки» as your own profile — a constellation of THEIR taste by genre. */}
            <TasteCard events={events} title={friend.name ? `Вкус ${friend.name}` : "Вкус"} />
          </>
        )}

        <div className="recs__section">в избранном</div>
        {loading ? (
          <p className="panelview__hint">Загружаем…</p>
        ) : isPrivate ? (
          <p className="profile__friends-empty">{friend.name || "Друг"} скрыл, что сохраняет.</p>
        ) : events.length > 0 ? (
          <CatalogFeed items={events} userPos={userPos} onSelect={onSelect} />
        ) : (
          <p className="profile__friends-empty">Пока ничего не сохранено.</p>
        )}
      </div>
    </div>
  );
}
