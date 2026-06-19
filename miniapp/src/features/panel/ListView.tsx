import { type UIEvent, useEffect, useRef, useState } from "react";

import { fetchEventsList, type EventItem, type ListSort } from "../../api/client";
import { goNowState } from "../../lib/datetime";
import type { LatLon } from "../../lib/distance";
import { IconClose } from "../../lib/icons";
import { CatalogFeed } from "./CatalogFeed";

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
  goNow,
  now,
  onSelect,
  onClose,
}: {
  open: boolean;
  baseParams: URLSearchParams;
  bbox: [number, number, number, number] | null;
  userPos?: LatLon | null;
  radiusKm?: number;
  goNow?: boolean; // «Сейчас» — filter to events you can still get to, client-side like the map
  now?: number;
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

  const loadingMoreRef = useRef(false);
  const loadMore = () => {
    // Synchronous reentrancy guard (state would be stale within a tick); never page while a
    // sort/filter reload is in flight (old offset under a new sort); stop when all are loaded
    // (the onScroll handler fires every tick, so this must short-circuit cheaply).
    if (loadingMoreRef.current || loading || (total > 0 && items.length >= total)) return;
    loadingMoreRef.current = true;
    setMore(true);
    fetchEventsList(build(items.length))
      .then((r) => {
        setItems((prev) => [...prev, ...r.items]);
        setTotal(r.total);
      })
      .catch(() => undefined)
      .finally(() => {
        loadingMoreRef.current = false;
        setMore(false);
      });
  };
  const loadMoreRef = useRef(loadMore);
  loadMoreRef.current = loadMore;

  // Infinite scroll: the React onScroll prop on the scroll div (below) is the primary loader —
  // React keeps it attached across re-renders (e.g. a theme toggle, which used to leave an
  // addEventListener'd handler stranded on a stale node). This observer is a secondary, earlier
  // preloader. Both call the LATEST loadMore via a ref; its guards make double-triggers no-ops.
  const canMore = items.length > 0 && items.length < total;
  // «Сейчас»: filter to live events client-side with the SAME goNowState the map uses (so the
  // list and the pins agree) — the list query has no server "now" (open_now is computed per item).
  const visible = goNow
    ? items.filter(
        (it) =>
          goNowState(it.date_start, it.date_end, it.open_now ?? null, now != null ? new Date(now) : new Date()).eligible,
      )
    : items;
  // A page can hold zero live events, which would dead-end the scroll loader — keep paging until
  // enough live events surface or a sane scan cap is hit.
  const searching = !!goNow && visible.length === 0 && canMore && items.length < 300;
  useEffect(() => {
    if (!canMore) return;
    const root = scrollRef.current;
    const sentinel = sentinelRef.current;
    if (!root || !sentinel) return;
    const io = new IntersectionObserver((entries) => entries[0].isIntersecting && loadMoreRef.current(), {
      root,
      rootMargin: "600px",
    });
    io.observe(sentinel);
    return () => io.disconnect();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [canMore]);

  // Auto-page while «Сейчас» is still hunting for live events across pages.
  useEffect(() => {
    if (!goNow || loading || more) return;
    if (visible.length < 16 && canMore && items.length < 300) loadMoreRef.current();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [goNow, visible.length, canMore, loading, more, items.length]);

  const onScrollLoad = (e: UIEvent<HTMLDivElement>) => {
    const el = e.currentTarget;
    if (el.scrollHeight - el.scrollTop - el.clientHeight < 900) loadMoreRef.current();
  };

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
          {goNow
            ? `${visible.length} ${plural(visible.length, "событие", "события", "событий")} можно сейчас`
            : `${total} ${plural(total, "событие", "события", "событий")} в этой области`}
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

      <div className="panelview__scroll" ref={scrollRef} onScroll={onScrollLoad}>
        {visible.length > 0 && <CatalogFeed items={visible} userPos={userPos} now={now} onSelect={onSelect} />}
        {!loading && error && <div className="listview__empty">Не удалось загрузить. Попробуй ещё раз.</div>}
        {!loading && !error && visible.length === 0 && !searching && (
          <div className="listview__empty">
            {goNow
              ? "Сейчас застать нечего — сними «сейчас» или подвинь карту."
              : "В этой области по фильтрам пусто. Подвинь карту или сними фильтры."}
          </div>
        )}
        {(loading || searching) && (
          <div className="listview__empty">{goNow ? "Ищем, что застать сейчас…" : "Загружаем…"}</div>
        )}
        {canMore && <div ref={sentinelRef} className="listview__sentinel" aria-hidden="true" />}
        {more && !searching && <div className="listview__empty">Загружаем ещё…</div>}
      </div>
    </div>
  );
}
