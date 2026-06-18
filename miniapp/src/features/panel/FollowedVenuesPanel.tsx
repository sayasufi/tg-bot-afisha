import { useEffect, useState, type CSSProperties } from "react";

import { fetchVenue, type EventItem, type VenueDetail } from "../../api/client";
import { categoryMeta } from "../../lib/categories";
import { IconClose } from "../../lib/icons";
import { CategoryIcon } from "../../lib/icons/category";
import { haptic } from "../../lib/telegram";
import { useVenueFollows } from "../../lib/venueFollows";
import { usePullToRefresh } from "../../lib/usePullToRefresh";
import { PullHint } from "./PullHint";

function plural(n: number, one: string, few: string, many: string): string {
  const m10 = n % 10;
  const m100 = n % 100;
  if (m10 === 1 && m100 !== 11) return one;
  if (m10 >= 2 && m10 <= 4 && !(m100 >= 12 && m100 <= 14)) return few;
  return many;
}

// The venue's dominant category (most events) — drives the row's category chip.
function topCategory(events: EventItem[]): string | null {
  if (!events.length) return null;
  const counts = new Map<string, number>();
  for (const e of events) counts.set(e.category, (counts.get(e.category) || 0) + 1);
  return [...counts.entries()].sort((a, b) => b[1] - a[1])[0][0];
}

// «Площадки» — the venues the user follows. Each row opens the venue page. (Venue headers
// are fetched per id; the follow list is small, so a handful of parallel fetches is fine.)
export function FollowedVenuesPanel({
  onOpenVenue,
  onClose,
}: {
  onOpenVenue: (venueId: number) => void;
  onClose: () => void;
}) {
  const follows = useVenueFollows();
  const idsKey = [...follows.ids].sort().join(",");
  const [venues, setVenues] = useState<VenueDetail[]>([]);
  const [loading, setLoading] = useState(true);

  const load = () => {
    const ids = idsKey ? idsKey.split(",") : [];
    if (!ids.length) {
      setVenues([]);
      setLoading(false);
      return;
    }
    setLoading(true);
    Promise.all(ids.map((id) => fetchVenue(id).catch(() => null)))
      .then((res) => setVenues(res.filter((v): v is VenueDetail => !!v)))
      .finally(() => setLoading(false));
  };
  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [idsKey]);
  const ptr = usePullToRefresh(() => load());

  return (
    <div className="panelview">
      <header className="panelview__head">
        <h2>Площадки</h2>
        <button type="button" className="panelview__close" aria-label="Закрыть" onClick={onClose}>
          <IconClose size={18} />
        </button>
      </header>
      <div className="panelview__scroll" ref={ptr.ref}>
        <PullHint pull={ptr.pull} armed={ptr.armed} refreshing={loading} />
        {venues.length > 0 ? (
          venues.map((v) => {
            const top = topCategory(v.events);
            const cat = top ? categoryMeta(top) : null;
            return (
              <button
                key={v.venue_id}
                type="button"
                className="vrow"
                onClick={() => {
                  haptic("light");
                  onOpenVenue(v.venue_id);
                }}
              >
                <span className="vrow__body">
                  <span className="vrow__name">{v.name}</span>
                  <span className="vrow__sub">
                    {cat && (
                      <span className="vrow__cat" style={{ "--cat": cat.color } as CSSProperties}>
                        <CategoryIcon cat={top} size={13} className="vrow__caticon" />
                        {cat.label}
                      </span>
                    )}
                    <span className="vrow__addr">{v.address || "Площадка"}</span>
                  </span>
                </span>
                {v.events.length > 0 && (
                  <span className="vrow__count">
                    <b className="vrow__num">{v.events.length}</b>
                    <span className="vrow__numlabel">{plural(v.events.length, "событие", "события", "событий")}</span>
                  </span>
                )}
              </button>
            );
          })
        ) : loading ? null : (
          <div className="favempty">
            <span className="favempty__glyph" aria-hidden="true" style={{ fontSize: 38, lineHeight: 1 }}>
              ⌂
            </span>
            <p className="panelview__hint">
              Отметь «Следить» на странице площадки — и она появится здесь, чтобы быстро вернуться к её афише.
            </p>
          </div>
        )}
      </div>
    </div>
  );
}
