import { type UIEvent, useEffect, useRef, useState } from "react";

import type { EventItem } from "../../api/client";
import { fetchCollection, type RailItem } from "../../api/recommend";
import { recentCategories } from "../../lib/affinity";
import { type LatLon } from "../../lib/distance";
import { IconClose } from "../../lib/icons";
import { EventCard } from "./EventCard";

const PAGE = 24;

const plural = (n: number, one: string, few: string, many: string) => {
  const m10 = n % 10;
  const m100 = n % 100;
  if (m10 === 1 && m100 !== 11) return one;
  if (m10 >= 2 && m10 <= 4 && (m100 < 12 || m100 > 14)) return few;
  return many;
};

// Full-screen detail behind a «Подборки» grid tile / «смотреть все»: the whole collection as a
// 2-column poster grid with the true «N событий» count + infinite scroll. `slug` is the bare
// collection slug ("date"), passed with the same personalisation params the feed used.
export function CollectionDetail({
  open,
  slug,
  title,
  subtitle,
  userPos,
  interests = [],
  city = null,
  onSelect,
  onClose,
}: {
  open: boolean;
  slug: string | null;
  title: string;
  subtitle?: string | null;
  userPos?: LatLon | null;
  interests?: string[];
  city?: string | null;
  onSelect: (i: EventItem) => void;
  onClose: () => void;
}) {
  const [items, setItems] = useState<RailItem[]>([]);
  const [count, setCount] = useState(0);
  const [loading, setLoading] = useState(false);
  const [more, setMore] = useState(false);
  const [error, setError] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);

  const lat = userPos?.[0] ?? null;
  const lon = userPos?.[1] ?? null;
  const interestsKey = [...interests].sort().join(",");

  // (Re)load page 0 whenever opened or the collection / personalisation changes.
  useEffect(() => {
    if (!open || !slug) return;
    setLoading(true);
    setError(false);
    setItems([]);
    scrollRef.current?.scrollTo({ top: 0 });
    const ctrl = new AbortController();
    fetchCollection(slug, { lat, lon, interests, recent: recentCategories(), city }, PAGE, 0, ctrl.signal)
      .then((r) => {
        setItems(r.items);
        setCount(r.count);
        setLoading(false);
      })
      .catch((e) => {
        if (e?.name !== "AbortError") {
          setItems([]);
          setCount(0);
          setLoading(false);
          setError(true);
        }
      });
    return () => ctrl.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, slug, lat, lon, interestsKey, city]);

  const loadingMoreRef = useRef(false);
  const loadMore = () => {
    if (!slug || loadingMoreRef.current || loading || (count > 0 && items.length >= count)) return;
    loadingMoreRef.current = true;
    setMore(true);
    fetchCollection(slug, { lat, lon, interests, recent: recentCategories(), city }, PAGE, items.length)
      .then((r) => {
        setItems((prev) => [...prev, ...r.items]);
        setCount(r.count);
      })
      .catch(() => undefined)
      .finally(() => {
        loadingMoreRef.current = false;
        setMore(false);
      });
  };
  const loadMoreRef = useRef(loadMore);
  loadMoreRef.current = loadMore;

  const onScroll = (e: UIEvent<HTMLDivElement>) => {
    const el = e.currentTarget;
    if (el.scrollHeight - el.scrollTop - el.clientHeight < 900) loadMoreRef.current();
  };

  if (!open) return null;

  return (
    <div className="panelview">
      <header className="panelview__head">
        <h2>{(title || "подборка").toLowerCase()}</h2>
        <button type="button" className="panelview__close" aria-label="Закрыть" onClick={onClose}>
          <IconClose size={18} />
        </button>
      </header>

      <div className="listview__bar">
        <span className="listview__count">
          {count} {plural(count, "событие", "события", "событий")}
          {subtitle ? ` · ${subtitle}` : ""}
        </span>
      </div>

      <div className="panelview__scroll" ref={scrollRef} onScroll={onScroll}>
        {items.length > 0 && (
          <div className="card-grid">
            {items.map((it, i) => (
              <EventCard key={it.event_id} item={it} index={i} userPos={userPos} onSelect={onSelect} />
            ))}
          </div>
        )}
        {loading && <div className="listview__empty">Загружаем…</div>}
        {!loading && error && <div className="listview__empty">Не удалось загрузить. Попробуй ещё раз.</div>}
        {!loading && !error && items.length === 0 && <div className="listview__empty">Пока пусто.</div>}
        {more && <div className="listview__empty">Загружаем ещё…</div>}
      </div>
    </div>
  );
}
