import type { EventItem } from "../../api/client";
import type { LatLon } from "../../lib/distance";
import { IconClose, IconHeart } from "../../lib/icons";
import { EventRow } from "./EventRow";

// Favourites you've hearted. Filtered from the loaded map set, soonest first.
export function FavoritesPanel({
  items,
  favIds,
  query,
  userPos,
  onSelect,
  onClose,
}: {
  items: EventItem[];
  favIds: Set<string>;
  query?: string;
  userPos?: LatLon | null;
  onSelect: (i: EventItem) => void;
  onClose: () => void;
}) {
  const favs = items
    .filter((it) => favIds.has(it.event_id))
    .sort((a, b) => (a.date_start || "").localeCompare(b.date_start || ""));

  return (
    <div className="panelview">
      <header className="panelview__head">
        <h2>Избранное</h2>
        <button type="button" className="panelview__close" aria-label="Закрыть" onClick={onClose}>
          <IconClose size={18} />
        </button>
      </header>
      <div className="panelview__scroll">
        {favs.length > 0 ? (
          favs.map((it, i) => (
            <EventRow key={it.event_id} item={it} index={i} query={query} userPos={userPos} onSelect={onSelect} />
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
