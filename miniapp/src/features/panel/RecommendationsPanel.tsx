import { useEffect, useMemo, useState, type CSSProperties } from "react";

import type { EventItem } from "../../api/client";
import { fetchRecommendations, type Rail } from "../../api/recommend";
import { recentCategories } from "../../lib/affinity";
import { categoryMeta } from "../../lib/categories";
import { type LatLon } from "../../lib/distance";
import { CategoryIcon, IconClose, IconGrid } from "../../lib/icons";
import { usePullToRefresh } from "../../lib/usePullToRefresh";
import { useRailScroll } from "../../lib/useRailScroll";
import { EventCard } from "./EventCard";
import { PullHint } from "./PullHint";

// The categories surfaced in the «По интересам» nav; the rest live behind «ещё» → all filters.
const NAV_CATS = ["theatre", "concert", "exhibition", "lecture", "cinema"];

const plural = (n: number, one: string, few: string, many: string) => {
  const m10 = n % 10;
  const m100 = n % 100;
  if (m10 === 1 && m100 !== 11) return one;
  if (m10 >= 2 && m10 <= 4 && (m100 < 12 || m100 > 14)) return few;
  return many;
};

const collectionSlug = (key: string) => key.replace(/^collection:/, "");

function RecRail({
  rail,
  userPos,
  onSelect,
  onMore,
}: {
  rail: Rail;
  userPos?: LatLon | null;
  onSelect: (i: EventItem) => void;
  onMore?: () => void;
}) {
  const trackRef = useRailScroll<HTMLDivElement>(0.93); // very gentle damping — just a touch slower than native
  return (
    <section className={`rail${rail.key === "for_you" ? " rail--hero" : ""}`}>
      <div className="rail__head">
        <span className="rail__title">{rail.title}</span>
        {rail.subtitle ? <span className="rail__sub">{rail.subtitle}</span> : null}
        {onMore ? (
          <button type="button" className="rail__more" onClick={onMore}>
            смотреть все →
          </button>
        ) : null}
      </div>
      <div className="rail__track" ref={trackRef}>
        {rail.items.map((it, i) => (
          <EventCard key={`${rail.key}-${it.event_id}`} item={it} index={i} userPos={userPos} onSelect={onSelect} />
        ))}
      </div>
    </section>
  );
}

// «Подборки» grid tile — a flat editorial entry into the full collection (not a card rail):
// name + the true «N событий» count + an arrow. Tap → the collection detail screen.
function CollectionTile({ rail, onOpen }: { rail: Rail; onOpen: (slug: string, title: string, sub: string | null) => void }) {
  const n = rail.count ?? rail.items.length;
  return (
    <button
      type="button"
      className="reccoll"
      onClick={() => onOpen(collectionSlug(rail.key), rail.title, rail.subtitle ?? null)}
    >
      <span className="reccoll__title">{rail.title}</span>
      <span className="reccoll__foot">
        <span className="reccoll__n">
          {n.toLocaleString("ru-RU")} {plural(n, "событие", "события", "событий")}
        </span>
        <span className="reccoll__arrow" aria-hidden="true">
          →
        </span>
      </span>
    </button>
  );
}

function RailSkeleton() {
  return (
    <>
      {Array.from({ length: 3 }).map((_, r) => (
        <section className="rail" key={r}>
          <div className="rail__head">
            <span className="skel skel--meta" style={{ width: 120 }} />
          </div>
          <div className="rail__track">
            {Array.from({ length: 4 }).map((_, i) => (
              <span key={i} className="rcard rcard--skel" style={{ "--i": i } as CSSProperties}>
                <span className="rcard__img skel" />
              </span>
            ))}
          </div>
        </section>
      ))}
    </>
  );
}

export function RecommendationsPanel({
  userPos,
  favCategories = [],
  refreshNonce = 0,
  city = null,
  onSelect,
  onOpenCollection,
  onPickCategory,
  onAllCategories,
  onClose,
}: {
  userPos?: LatLon | null;
  favCategories?: string[];
  refreshNonce?: number;
  city?: string | null;
  onSelect: (i: EventItem) => void;
  onOpenCollection: (slug: string, title: string, subtitle: string | null) => void;
  onPickCategory: (category: string) => void;
  onAllCategories: () => void;
  onClose: () => void;
}) {
  const [rails, setRails] = useState<Rail[]>([]);
  const [collections, setCollections] = useState<Rail[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [localNonce, setLocalNonce] = useState(0);
  const retry = () => setLocalNonce((n) => n + 1);
  const ptr = usePullToRefresh(retry);

  // Re-fetch when location, interests, or a refresh signal changes. The string
  // key avoids refetching on every render from the userPos array identity.
  const lat = userPos?.[0] ?? null;
  const lon = userPos?.[1] ?? null;
  const interestsKey = useMemo(() => [...favCategories].sort().join(","), [favCategories]);

  useEffect(() => {
    setLoading(true);
    setError(false);
    const ctrl = new AbortController();
    fetchRecommendations({ lat, lon, interests: interestsKey ? interestsKey.split(",") : [], recent: recentCategories(), city }, ctrl.signal)
      .then((r) => {
        setRails(r.rails);
        setCollections(r.collections);
        setLoading(false);
      })
      .catch((e) => {
        if (e?.name !== "AbortError") {
          // A failed fetch is NOT an empty result — surface a retry, don't render "пусто".
          setRails([]);
          setCollections([]);
          setLoading(false);
          setError(true);
        }
      });
    return () => ctrl.abort();
  }, [lat, lon, interestsKey, refreshNonce, localNonce, city]);

  const hasContent = rails.length > 0 || collections.length > 0;
  const empty = !loading && !error && !hasContent;
  // The first collection (Свидание — always present) gets a featured card rail; the rest become
  // the «Подборки» grid of entry tiles.
  const featured = collections[0] ?? null;
  const gridCollections = collections.slice(1);

  return (
    <div className="panelview">
      <header className="panelview__head">
        <h2>подборка</h2>
        <button type="button" className="panelview__close" aria-label="Закрыть" onClick={onClose}>
          <IconClose size={18} />
        </button>
      </header>
      <div className="panelview__scroll panelview__scroll--rails" ref={ptr.ref}>
        <PullHint pull={ptr.pull} armed={ptr.armed} refreshing={loading} />
        {loading && rails.length === 0 && <RailSkeleton />}
        {error && (
          <div className="favempty">
            <p className="panelview__hint">Не удалось загрузить подборку. Попробуй ещё раз.</p>
            <button type="button" className="btn btn--primary" onClick={retry}>
              Повторить
            </button>
          </div>
        )}
        {empty && <p className="panelview__empty">пока нечего показать</p>}

        {/* 1) Personal hero. */}
        {rails[0] && <RecRail key={rails[0].key} rail={rails[0]} userPos={userPos} onSelect={onSelect} />}

        {/* 2) «Подборки» — a grid of collection entry tiles (the rest of the collections). */}
        {gridCollections.length > 0 && (
          <section className="rail">
            <div className="rail__head">
              <span className="rail__title">Подборки</span>
            </div>
            <div className="recgrid">
              {gridCollections.map((rail) => (
                <CollectionTile key={rail.key} rail={rail} onOpen={onOpenCollection} />
              ))}
            </div>
          </section>
        )}

        {/* 3) Featured collection (Свидание) as a full card rail → its detail via «смотреть все». */}
        {featured && (
          <RecRail
            key={featured.key}
            rail={featured}
            userPos={userPos}
            onSelect={onSelect}
            onMore={() => onOpenCollection(collectionSlug(featured.key), featured.title, featured.subtitle ?? null)}
          />
        )}

        {/* 4) «По интересам» — jump to the map filtered by a category. */}
        {hasContent && (
          <section className="rail">
            <div className="rail__head">
              <span className="rail__title">По интересам</span>
              <span className="rail__sub">выберите категорию</span>
              <button type="button" className="rail__more" onClick={onAllCategories}>
                все категории →
              </button>
            </div>
            <div className="reccats">
              {NAV_CATS.map((cat) => (
                <button key={cat} type="button" className="reccat" onClick={() => onPickCategory(cat)}>
                  <CategoryIcon cat={cat} size={22} className="reccat__icon" />
                  <span className="reccat__label">{categoryMeta(cat).label}</span>
                </button>
              ))}
              <button type="button" className="reccat" onClick={onAllCategories}>
                <IconGrid size={22} className="reccat__icon" />
                <span className="reccat__label">ещё</span>
              </button>
            </div>
          </section>
        )}

        {/* 5) The engine's themed rails (Рядом, Сегодня, На выходных, Популярное, по категориям). */}
        {rails.slice(1).map((rail) => (
          <RecRail key={rail.key} rail={rail} userPos={userPos} onSelect={onSelect} />
        ))}
      </div>
    </div>
  );
}
