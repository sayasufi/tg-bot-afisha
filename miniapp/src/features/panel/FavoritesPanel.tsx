import { useEffect, useState } from "react";

import { fetchEventsByIds, type EventItem } from "../../api/client";
import type { LatLon } from "../../lib/distance";
import { IconClose, IconHeart } from "../../lib/icons";
import { usePullToRefresh } from "../../lib/usePullToRefresh";
import { CatalogFeed } from "./CatalogFeed";
import { PullHint } from "./PullHint";

// Favourites — fetched by id from the server (independent of the map's loaded set, so the
// list always matches the count), in the same full-bleed poster format as the list view.
export function FavoritesPanel({
  favIds,
  userPos,
  onSelect,
  onClose,
}: {
  favIds: Set<string>;
  userPos?: LatLon | null;
  onSelect: (i: EventItem) => void;
  onClose: () => void;
}) {
  const [favs, setFavs] = useState<EventItem[]>([]);
  const [loading, setLoading] = useState(true);
  const idsKey = [...favIds].sort().join(",");

  const load = () => {
    const ids = idsKey ? idsKey.split(",") : [];
    if (!ids.length) {
      setFavs([]);
      setLoading(false);
      return;
    }
    setLoading(true);
    fetchEventsByIds(ids, userPos ?? null)
      .then(setFavs)
      .finally(() => setLoading(false));
  };
  // Mounted only while the favourites view is open; (re)fetch on open and when the set changes.
  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [idsKey]);

  const ptr = usePullToRefresh(() => load());

  return (
    <div className="panelview listview">
      <header className="panelview__head">
        <h2>Избранное</h2>
        <button type="button" className="panelview__close" aria-label="Закрыть" onClick={onClose}>
          <IconClose size={18} />
        </button>
      </header>
      <div className="panelview__scroll" ref={ptr.ref}>
        <PullHint pull={ptr.pull} armed={ptr.armed} refreshing={loading} />
        {favs.length > 0 ? (
          <CatalogFeed items={favs} userPos={userPos} onSelect={onSelect} />
        ) : loading ? null : (
          <div className="favempty">
            <IconHeart size={40} className="favempty__glyph" />
            <p className="panelview__hint">
              Отмечай события сердечком в карточке — они соберутся здесь, чтобы вернуться к ним позже.
            </p>
          </div>
        )}
      </div>
    </div>
  );
}
