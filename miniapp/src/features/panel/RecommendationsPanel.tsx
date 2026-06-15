import { useEffect, useMemo, useState, type CSSProperties } from "react";

import { fetchRecommendations, type Rail, type RailItem } from "../../api/recommend";
import { recentCategories } from "../../lib/affinity";
import { categoryMeta } from "../../lib/categories";
import { formatWhenShort, isLiveNow } from "../../lib/datetime";
import { distanceLabel, formatDistance, type LatLon } from "../../lib/distance";
import { CategoryIcon, IconClose } from "../../lib/icons";
import { safeHttpUrl } from "../../lib/url";
import { usePullToRefresh } from "../../lib/usePullToRefresh";
import { PullHint } from "./PullHint";

function priceLabel(p: number | null | undefined): { text: string; free: boolean } | null {
  if (p == null) return null;
  if (p <= 0) return { text: "бесплатно", free: true };
  return { text: `от ${Math.round(p)} ₽`, free: false };
}

function RecCard({ item, userPos, onSelect }: { item: RailItem; userPos?: LatLon | null; onSelect: (i: RailItem) => void }) {
  const meta = categoryMeta(item.category);
  const live = isLiveNow(item.date_start, item.date_end, item.venue_hours);
  const img = safeHttpUrl(item.primary_image_url);
  const dist =
    item.distance_m != null
      ? formatDistance(item.distance_m)
      : item.lat != null && item.lon != null
        ? distanceLabel(userPos, [item.lat, item.lon])
        : null;
  const when = formatWhenShort(item.date_start, item.date_end);
  const price = priceLabel(item.price_min);
  return (
    <button
      type="button"
      className="rcard"
      style={{ "--cat": meta.color } as CSSProperties}
      aria-label={`${item.title}. ${meta.label}. ${when}${dist ? `. ${dist}` : ""}${price ? `. ${price.text}` : ""}`}
      onClick={() => onSelect(item)}
    >
      <span className="rcard__img">
        {img ? (
          <img src={img} alt={item.title} loading="lazy" decoding="async" />
        ) : (
          <span className="rcard__ph">
            <CategoryIcon cat={item.category} size={30} />
          </span>
        )}
        <span className="rcard__scrim" aria-hidden="true" />
        {live && (
          <span className="rcard__live">
            <i className="rcard__livedot" aria-hidden="true" />
            сейчас
          </span>
        )}
        {price && <span className={`rcard__price${price.free ? " rcard__price--free" : ""}`}>{price.text}</span>}
      </span>
      <span className="rcard__title">{item.title}</span>
      <span className="rcard__meta">
        {when}
        {dist ? ` · ${dist}` : ""}
      </span>
    </button>
  );
}

function RecRail({ rail, userPos, onSelect }: { rail: Rail; userPos?: LatLon | null; onSelect: (i: RailItem) => void }) {
  return (
    <section className={`rail${rail.key === "for_you" ? " rail--hero" : ""}`}>
      <div className="rail__head">
        <span className="rail__title">{rail.title}</span>
        {rail.subtitle ? <span className="rail__sub">{rail.subtitle}</span> : null}
      </div>
      <div className="rail__track">
        {rail.items.map((it) => (
          <RecCard key={`${rail.key}-${it.event_id}`} item={it} userPos={userPos} onSelect={onSelect} />
        ))}
      </div>
    </section>
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
  onSelect,
  onClose,
}: {
  userPos?: LatLon | null;
  favCategories?: string[];
  refreshNonce?: number;
  onSelect: (i: RailItem) => void;
  onClose: () => void;
}) {
  const [rails, setRails] = useState<Rail[]>([]);
  const [loading, setLoading] = useState(true);
  const [localNonce, setLocalNonce] = useState(0);
  const ptr = usePullToRefresh(() => setLocalNonce((n) => n + 1));

  // Re-fetch when location, interests, or a refresh signal changes. The string
  // key avoids refetching on every render from the userPos array identity.
  const lat = userPos?.[0] ?? null;
  const lon = userPos?.[1] ?? null;
  const interestsKey = useMemo(() => [...favCategories].sort().join(","), [favCategories]);

  useEffect(() => {
    setLoading(true);
    const ctrl = new AbortController();
    fetchRecommendations({ lat, lon, interests: interestsKey ? interestsKey.split(",") : [], recent: recentCategories() }, ctrl.signal)
      .then((r) => {
        setRails(r.rails);
        setLoading(false);
      })
      .catch((e) => {
        if (e?.name !== "AbortError") {
          setRails([]);
          setLoading(false);
        }
      });
    return () => ctrl.abort();
  }, [lat, lon, interestsKey, refreshNonce, localNonce]);

  const empty = !loading && rails.length === 0;

  return (
    <div className="panelview">
      <header className="panelview__head">
        <h2>Подборка</h2>
        <button type="button" className="panelview__close" aria-label="Закрыть" onClick={onClose}>
          <IconClose size={18} />
        </button>
      </header>
      <div className="panelview__scroll panelview__scroll--rails" ref={ptr.ref}>
        <PullHint pull={ptr.pull} armed={ptr.armed} refreshing={loading} />
        {loading && rails.length === 0 && <RailSkeleton />}
        {empty && <p className="panelview__empty">пока нечего показать</p>}
        {rails.map((rail) => (
          <RecRail key={rail.key} rail={rail} userPos={userPos} onSelect={onSelect} />
        ))}
      </div>
    </div>
  );
}
