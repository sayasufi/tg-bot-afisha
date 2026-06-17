import { useEffect, useRef, useState } from "react";

import { fetchEventsList, type EventItem, type ListSort } from "../../api/client";
import type { LatLon } from "../../lib/distance";
import { IconClose } from "../../lib/icons";
import { EventListRow } from "./EventListRow";

const PAGE = 20;
const SORTS: { key: ListSort; label: string }[] = [
  { key: "date", label: "По дате" },
  { key: "distance", label: "Рядом" },
  { key: "popularity", label: "Популярные" },
  { key: "price", label: "Дешевле" },
];

const plural = (n: number, one: string, few: string, many: string) => {
  const m10 = n % 10;
  const m100 = n % 100;
  if (m10 === 1 && m100 !== 11) return one;
  if (m10 >= 2 && m10 <= 4 && (m100 < 12 || m100 > 14)) return few;
  return many;
};

// The "list view" of the map: every event in the current map area, by the same filters,
// browsable with thumbnails, sortable, paginated. bbox is frozen at open time.
export function ListView({
  open,
  baseParams,
  bbox,
  userPos,
  radiusKm,
  onSelect,
  onClose,
}: {
  open: boolean;
  baseParams: URLSearchParams;
  bbox: [number, number, number, number] | null;
  userPos?: LatLon | null;
  radiusKm?: number;
  onSelect: (i: EventItem) => void;
  onClose: () => void;
}) {
  const [sort, setSort] = useState<ListSort>("date");
  const [items, setItems] = useState<EventItem[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [more, setMore] = useState(false);
  const [error, setError] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);
  const sentinelRef = useRef<HTMLDivElement>(null);

  const bboxKey = bbox ? bbox.join(",") : "";
  const paramsKey = baseParams.toString();

  const build = (offset: number) => {
    const p = new URLSearchParams(baseParams);
    if (bbox) p.set("bbox", bboxKey);
    p.set("sort", sort);
    if (userPos) {
      p.set("lat", String(userPos[0]));
      p.set("lon", String(userPos[1]));
    }
    if (radiusKm && radiusKm > 0) p.set("radius_km", String(radiusKm));
    p.set("limit", String(PAGE));
    p.set("offset", String(offset));
    return p;
  };

  // (Re)load the first page whenever opened, or the sort / bbox / filters change.
  useEffect(() => {
    if (!open || !bbox) return;
    setLoading(true);
    setError(false);
    // Switching sort (or filters/bbox) reloads from page 0 — jump back to the top so the
    // user sees the new first results, not their old scroll position.
    scrollRef.current?.scrollTo({ top: 0 });
    const ctrl = new AbortController();
    fetchEventsList(build(0), ctrl.signal)
      .then((r) => {
        setItems(r.items);
        setTotal(r.total);
        setLoading(false);
      })
      .catch((e) => {
        if (e?.name !== "AbortError") {
          setItems([]);
          setTotal(0);
          setLoading(false);
          setError(true);
        }
      });
    return () => ctrl.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, sort, bboxKey, paramsKey]);

  const loadMore = () => {
    if (more) return;
    setMore(true);
    fetchEventsList(build(items.length))
      .then((r) => {
        setItems((prev) => [...prev, ...r.items]);
        setTotal(r.total);
        setMore(false);
      })
      .catch(() => setMore(false));
  };

  // Infinite scroll: auto-load the next page when a sentinel near the list's end comes
  // into view (no "показать ещё" tap). Re-binds with a fresh loadMore as items grow.
  const canMore = items.length > 0 && items.length < total;
  useEffect(() => {
    if (!canMore) return;
    const root = scrollRef.current;
    const sentinel = sentinelRef.current;
    if (!root || !sentinel) return;
    const io = new IntersectionObserver((entries) => entries[0].isIntersecting && loadMore(), {
      root,
      rootMargin: "500px",
    });
    io.observe(sentinel);
    return () => io.disconnect();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [canMore, items.length, sort, bboxKey]);

  if (!open) return null;

  return (
    <div className="panelview listview">
      <header className="panelview__head">
        <h2>списком</h2>
        <button type="button" className="panelview__close" aria-label="Закрыть" onClick={onClose}>
          <IconClose size={18} />
        </button>
      </header>

      <div className="listview__bar">
        <span className="listview__count">
          {total} {plural(total, "событие", "события", "событий")} в этой области
        </span>
        <div className="listview__sorts" role="tablist" aria-label="Сортировка">
          {SORTS.map((s) => (
            <button
              key={s.key}
              type="button"
              role="tab"
              aria-selected={sort === s.key}
              className={`listview__sort${sort === s.key ? " listview__sort--on" : ""}`}
              onClick={() => setSort(s.key)}
            >
              {s.label}
            </button>
          ))}
        </div>
      </div>

      <div className="panelview__scroll" ref={scrollRef}>
        {items.map((it, i) => (
          <EventListRow key={it.event_id} item={it} index={i} userPos={userPos} onSelect={onSelect} />
        ))}
        {!loading && error && <div className="listview__empty">Не удалось загрузить. Попробуй ещё раз.</div>}
        {!loading && !error && items.length === 0 && <div className="listview__empty">В этой области по фильтрам пусто. Подвинь карту или сними фильтры.</div>}
        {loading && <div className="listview__empty">Загружаем…</div>}
        {canMore && <div ref={sentinelRef} className="listview__sentinel" aria-hidden="true" />}
        {more && <div className="listview__empty">Загружаем ещё…</div>}
      </div>
    </div>
  );
}
