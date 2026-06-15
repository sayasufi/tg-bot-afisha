import { useEffect, useMemo, useState, type CSSProperties } from "react";

import type { EventItem } from "../../api/client";
import { fetchRecommendations, type Rail } from "../../api/recommend";
import { recentCategories } from "../../lib/affinity";
import { type LatLon } from "../../lib/distance";
import { IconClose } from "../../lib/icons";
import { usePullToRefresh } from "../../lib/usePullToRefresh";
import { EventCard } from "./EventCard";
import { PullHint } from "./PullHint";

function RecRail({ rail, userPos, onSelect }: { rail: Rail; userPos?: LatLon | null; onSelect: (i: EventItem) => void }) {
  return (
    <section className={`rail${rail.key === "for_you" ? " rail--hero" : ""}`}>
      <div className="rail__head">
        <span className="rail__title">{rail.title}</span>
        {rail.subtitle ? <span className="rail__sub">{rail.subtitle}</span> : null}
      </div>
      <div className="rail__track">
        {rail.items.map((it) => (
          <EventCard key={`${rail.key}-${it.event_id}`} item={it} userPos={userPos} onSelect={onSelect} />
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
  onSelect: (i: EventItem) => void;
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
