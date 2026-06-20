import { useEffect, useState } from "react";

import { fetchEventsByIds, type EventItem } from "../../api/client";
import type { LatLon } from "../../lib/distance";
import { IconClose, IconGoing } from "../../lib/icons";
import { usePullToRefresh } from "../../lib/usePullToRefresh";
import { CatalogFeed } from "./CatalogFeed";
import { PullHint } from "./PullHint";

// «Я иду» — the events the user RSVP'd to, fetched by id from the server (independent of the map's
// loaded set, so the list always matches the count), in the same full-bleed poster format.
export function GoingPanel({
  goingIds,
  userPos,
  onSelect,
  onClose,
}: {
  goingIds: Set<string>;
  userPos?: LatLon | null;
  onSelect: (i: EventItem) => void;
  onClose: () => void;
}) {
  const [items, setItems] = useState<EventItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const idsKey = [...goingIds].sort().join(",");

  const load = () => {
    const ids = idsKey ? idsKey.split(",") : [];
    setError(false);
    if (!ids.length) {
      setItems([]);
      setLoading(false);
      return;
    }
    setLoading(true);
    fetchEventsByIds(ids, userPos ?? null)
      .then((r) => {
        setItems(r);
        setLoading(false);
      })
      // A failed fetch is NOT an empty list — keep the count, show a retry.
      .catch(() => {
        setLoading(false);
        setError(true);
      });
  };
  // Mounted only while the going view is open; (re)fetch on open and when the set changes.
  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [idsKey]);

  const ptr = usePullToRefresh(() => load());

  return (
    <div className="panelview listview">
      <header className="panelview__head">
        <h2>я иду</h2>
        <button type="button" className="panelview__close" aria-label="Закрыть" onClick={onClose}>
          <IconClose size={18} />
        </button>
      </header>
      <div className="panelview__scroll" ref={ptr.ref}>
        <PullHint pull={ptr.pull} armed={ptr.armed} refreshing={loading} />
        {items.length > 0 ? (
          <CatalogFeed items={items} userPos={userPos} onSelect={onSelect} />
        ) : loading ? null : error ? (
          <div className="favempty">
            <p className="panelview__hint">Не удалось загрузить. Попробуй ещё раз.</p>
            <button type="button" className="btn btn--primary" onClick={load}>
              Повторить
            </button>
          </div>
        ) : (
          <div className="favempty">
            <IconGoing size={40} className="favempty__glyph" />
            <p className="panelview__hint">
              Жми «Я иду» в карточке события — всё, на что ты собрался, соберётся здесь, и мы напомним перед началом.
            </p>
          </div>
        )}
      </div>
    </div>
  );
}
