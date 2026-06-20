import { useEffect, useState, type CSSProperties } from "react";

import { fetchVenue, type VenueDetail } from "../../api/client";
import { categoryMeta } from "../../lib/categories";
import { formatWhenShort } from "../../lib/datetime";
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
  const [error, setError] = useState(false);

  const load = () => {
    const ids = idsKey ? idsKey.split(",") : [];
    setError(false);
    if (!ids.length) {
      setVenues([]);
      setLoading(false);
      return;
    }
    setLoading(true);
    // Per-id .catch keeps the panel resilient to a single bad venue, but if EVERY fetch
    // failed (a real outage) that's an error, not "you follow nothing" — surface a retry.
    Promise.all(ids.map((id) => fetchVenue(id).catch(() => null)))
      .then((res) => {
        const ok = res.filter((v): v is VenueDetail => !!v);
        setVenues(ok);
        setError(ok.length === 0);
        setLoading(false);
      });
  };
  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [idsKey]);
  const ptr = usePullToRefresh(() => load());

  return (
    <div className="panelview">
      <header className="panelview__head">
        <h2>площадки</h2>
        <button type="button" className="panelview__close" aria-label="Закрыть" onClick={onClose}>
          <IconClose size={18} />
        </button>
      </header>
      <div className="panelview__scroll" ref={ptr.ref}>
        <PullHint pull={ptr.pull} armed={ptr.armed} refreshing={loading} />
        {venues.length > 0 ? (
          venues.map((v) => {
            // v.events is sorted soonest-first by the API → the next/ongoing event at this venue.
            const next = v.events[0] ?? null;
            const cat = next ? categoryMeta(next.category) : null;
            const newN = v.new_count ?? 0;
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
                  <span className="vrow__top">
                    <span className="vrow__name">{v.name}</span>
                    {/* Show «+N новых» only as a genuine DELTA (some — not all — events are new). While the
                        whole catalogue is freshly ingested (every event «new»), this stays dormant and
                        self-activates as venues accumulate older events. */}
                    {newN > 0 && newN < v.events.length && (
                      <span className="vrow__new">+{newN} {plural(newN, "новое", "новых", "новых")}</span>
                    )}
                  </span>
                  {next ? (
                    <span className="vrow__next">
                      {cat && (
                        <span className="vrow__cat" style={{ "--cat": cat.color } as CSSProperties}>
                          <CategoryIcon cat={next.category} size={13} className="vrow__caticon" />
                          {cat.label}
                        </span>
                      )}
                      <span className="vrow__nexttitle">{next.title}</span>
                      <span className="vrow__nextdate">{formatWhenShort(next.date_start, next.date_end)}</span>
                    </span>
                  ) : (
                    <span className="vrow__next">
                      <span className="vrow__addr">{v.address || "Площадка"}</span>
                    </span>
                  )}
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
        ) : loading ? null : error ? (
          <div className="favempty">
            <p className="panelview__hint">Не удалось загрузить площадки. Попробуй ещё раз.</p>
            <button type="button" className="btn btn--primary" onClick={load}>
              Повторить
            </button>
          </div>
        ) : (
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
