import type { EventItem } from "../../api/client";
import type { LatLon } from "../../lib/distance";
import { IconClose, IconHeart } from "../../lib/icons";
import { usePullToRefresh } from "../../lib/usePullToRefresh";
import { EventListRow } from "./EventListRow";
import { PullHint } from "./PullHint";

// Favourites you've hearted — same full-bleed poster format as the list view, soonest first.
export function FavoritesPanel({
  items,
  favIds,
  userPos,
  loading = false,
  onRefresh,
  onSelect,
  onClose,
}: {
  items: EventItem[];
  favIds: Set<string>;
  userPos?: LatLon | null;
  loading?: boolean;
  onRefresh?: () => void;
  onSelect: (i: EventItem) => void;
  onClose: () => void;
}) {
  const ptr = usePullToRefresh(() => onRefresh?.());
  const favs = items
    .filter((it) => favIds.has(it.event_id))
    .sort((a, b) => (a.date_start || "").localeCompare(b.date_start || ""));

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
          favs.map((it, i) => (
            <EventListRow key={it.event_id} item={it} index={i} userPos={userPos} onSelect={onSelect} />
          ))
        ) : (
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
