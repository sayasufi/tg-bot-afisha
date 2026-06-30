import { useEffect, useState } from "react";

import { fetchVenue, type EventItem, type VenueDetail } from "../../api/client";
import type { LatLon } from "../../lib/distance";
import { IconClose } from "../../lib/icons";
import { haptic } from "../../lib/telegram";
import { showToast } from "../../lib/toast";
import { useVenueFollows } from "../../lib/venueFollows";
import { EventListRow } from "../panel/EventListRow";

function plural(n: number, one: string, few: string, many: string): string {
  const m10 = n % 10;
  const m100 = n % 100;
  if (m10 === 1 && m100 !== 11) return one;
  if (m10 >= 2 && m10 <= 4 && !(m100 >= 12 && m100 <= 14)) return few;
  return many;
}

// The venue page — opened by tapping the place in an event sheet. Shows the venue's upcoming
// events (the same poster rows as the list/favorites) and a "Следить" follow toggle.
export function VenueSheet({
  venueId,
  userPos,
  now,
  onSelect,
  onClose,
}: {
  venueId: number;
  userPos?: LatLon | null;
  now?: number;
  onSelect: (i: EventItem) => void;
  onClose: () => void;
}) {
  const [venue, setVenue] = useState<VenueDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [reloadNonce, setReloadNonce] = useState(0);
  const follows = useVenueFollows();
  const id = String(venueId);
  const followed = follows.has(id);

  useEffect(() => {
    setVenue(null);
    setLoading(true);
    setError(false);
    const ctrl = new AbortController();
    fetchVenue(venueId, ctrl.signal)
      .then((v) => {
        setVenue(v);
        setLoading(false);
      })
      // A failed load is NOT "no upcoming events" — show a retry instead of a false empty.
      .catch((e) => {
        if (e?.name !== "AbortError") {
          setLoading(false);
          setError(true);
        }
      });
    return () => ctrl.abort();
  }, [venueId, reloadNonce]);

  const onFollow = () => {
    haptic("light");
    // Честно про триггер: подписка кормит еженедельную подборку «новое на твоих площадках» (не мгновенный пуш).
    showToast(followed ? "Больше не следите за площадкой" : "Следите · новое пришлю в подборке на выходные", {
      icon: "bell",
      tone: followed ? "muted" : "good",
    });
    follows.toggle(id);
  };

  const events = venue?.events ?? [];
  return (
    <div className="panelview listview venuesheet">
      <div className="venuesheet__head">
        <div className="venuesheet__top">
          <span className="venuesheet__kicker">Площадка</span>
          <button type="button" className="venuesheet__close" aria-label="Закрыть" onClick={onClose}>
            <IconClose size={18} />
          </button>
        </div>
        <h2 className="venuesheet__title">{venue?.name ?? "Площадка"}</h2>
        <div className="venuesheet__bar">
          <span className="venuesheet__addr">
            {venue?.address || "Площадка"}
            {events.length > 0 && (
              <span className="venuesheet__count">
                {" · "}
                {events.length} {plural(events.length, "событие", "события", "событий")}
              </span>
            )}
          </span>
          <button
            type="button"
            className={`venuesheet__follow${followed ? " venuesheet__follow--on" : ""}`}
            aria-pressed={followed}
            onClick={onFollow}
          >
            {followed ? "Слежу" : "Следить"}
          </button>
        </div>
      </div>
      <div className="panelview__scroll">
        {loading && !venue ? null : error ? (
          <div className="favempty">
            <p className="panelview__hint">Не удалось загрузить площадку. Попробуй ещё раз.</p>
            <button type="button" className="btn btn--primary" onClick={() => setReloadNonce((n) => n + 1)}>
              Повторить
            </button>
          </div>
        ) : events.length > 0 ? (
          events.map((it, i) => (
            <EventListRow key={it.event_id} item={it} index={i} userPos={userPos} now={now} onSelect={onSelect} />
          ))
        ) : (
          <p className="panelview__empty">пока нет предстоящих событий</p>
        )}
      </div>
    </div>
  );
}
