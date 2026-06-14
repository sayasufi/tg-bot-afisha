// Lightweight map-screen states: a top loading bar, an empty-result card, a
// one-time coach hint, and the radar sweep on locate.

// Radar sweep from the user on each locate tap — echoes the logo / "вокруг тебя".
// Keyed by the locate nonce in App so it remounts and replays each tap.
export function RadarPing({ nonce }: { nonce: number }) {
  if (!nonce) return null;
  return (
    <div className="radar" aria-hidden="true">
      <span />
      <span />
      <span />
    </div>
  );
}

export function LoadingBar({ show }: { show: boolean }) {
  if (!show) return null;
  return (
    <div className="loadbar" aria-hidden="true">
      <span />
    </div>
  );
}

// First-load veil: a soft shimmer + "developing" caption while the very first
// set of events is being fetched (the map tiles fade in underneath).
export function MapShimmer({ show }: { show: boolean }) {
  if (!show) return null;
  return (
    <div className="mapshimmer" role="status" aria-label="Загрузка">
      <span className="dotfield" aria-hidden="true" />
      <div className="mapshimmer__card">
        <span className="mapshimmer__bar" />
        <span className="mapshimmer__cap">Проявляем окрест…</span>
      </div>
    </div>
  );
}

type EmptyFilters = { q: string; categories: string[]; priceMax: string; radiusKm: number };

export function EmptyState({
  filters,
  radiusActive,
  onReset,
  onWiden,
}: {
  filters: EmptyFilters;
  radiusActive: boolean;
  onReset: () => void;
  onWiden: () => void;
}) {
  // Offer the smallest useful loosening first: drop the radius/category/price
  // narrowing (keeping date + search), and only then a full reset.
  const narrowed = radiusActive || filters.categories.length > 0 || !!filters.priceMax;
  const text = radiusActive
    ? "В этом радиусе пока пусто. Увеличь расстояние или сними другие фильтры — рядом наверняка что-то есть."
    : narrowed
      ? "Под выбранные категории и цену ничего не нашлось. Можно ослабить фильтры — события рядом вернутся."
      : "Под эти фильтры экспозиция пуста. Расширь даты или поиск — и события вернутся.";

  return (
    <div className="emptystate" role="status">
      <span className="dotfield" aria-hidden="true" />
      <div className="emptystate__card">
        <svg className="emptystate__mark" viewBox="0 0 48 48" aria-hidden="true">
          <circle cx="21" cy="21" r="13" fill="none" stroke="currentColor" strokeWidth="3" />
          <line x1="31" y1="31" x2="42" y2="42" stroke="currentColor" strokeWidth="3" strokeLinecap="round" />
        </svg>
        <span className="kicker kicker--code emptystate__kicker">Окрест · Москва</span>
        <div className="emptystate__title serif">
          Тишина в <em>зале</em>
        </div>
        <p className="emptystate__text">{text}</p>
        {narrowed && (
          <button type="button" className="btn btn--primary emptystate__btn" onClick={onWiden}>
            Расширить поиск
          </button>
        )}
        <button type="button" className={`btn emptystate__btn${narrowed ? " btn--ghost" : " btn--primary"}`} onClick={onReset}>
          Сбросить всё
        </button>
      </div>
    </div>
  );
}

export function Coach({ onDismiss }: { onDismiss: () => void }) {
  return (
    <button type="button" className="coach" onClick={onDismiss} aria-label="Понятно">
      Нажми — покажу, что вокруг
    </button>
  );
}
