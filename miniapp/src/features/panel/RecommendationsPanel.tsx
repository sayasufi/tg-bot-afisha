import { useEffect, useMemo, useState, type CSSProperties } from "react";

import { fetchEventsByIds, fetchVenue, type EventItem, type VenueDetail } from "../../api/client";
import { fetchRecommendations, type Rail } from "../../api/recommend";
import { fetchFriendsActivity, type Friend, type FriendActivity } from "../../api/users";
import { recentCategories } from "../../lib/affinity";
import { categoryMeta } from "../../lib/categories";
import { formatWhenShort } from "../../lib/datetime";
import { type LatLon } from "../../lib/distance";
import { CategoryIcon, IconClose, IconGrid } from "../../lib/icons";
import { safeHttpUrl } from "../../lib/url";
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

function shortTitle(t: string): string {
  const s = (t || "").trim();
  const m = s.match(/^(.{6,}?)(?:\.\s|\s[—–·|]\s)/);
  return (m ? m[1] : s).trim();
}

function timeAgo(iso: string): string {
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return "";
  const sec = Math.max(0, (Date.now() - t) / 1000);
  if (sec < 90) return "только что";
  const min = Math.round(sec / 60);
  if (min < 60) return `${min} мин назад`;
  const hr = Math.round(min / 60);
  if (hr < 24) return `${hr} ч назад`;
  const d = Math.round(hr / 24);
  if (d === 1) return "вчера";
  if (d < 7) return `${d} дн назад`;
  return `${Math.round(d / 7)} нед назад`;
}

function FriendAvatar({ f }: { f: Friend }) {
  const av = safeHttpUrl(f.photo_url);
  return (
    <span className="profile__friend-av" style={av ? { backgroundImage: `url("${av}")` } : undefined}>
      {av ? "" : (f.name || f.username || "?").slice(0, 1).toUpperCase()}
    </span>
  );
}

function FriendActivityRow({ a, onOpen }: { a: FriendActivity; onOpen: (e: EventItem) => void }) {
  const who = a.friend.name || (a.friend.username ? `@${a.friend.username}` : "друг");
  const cover = safeHttpUrl(a.event.primary_image_url);
  return (
    <button type="button" className="friends__act" onClick={() => onOpen(a.event)}>
      <FriendAvatar f={a.friend} />
      <span className="friends__act-body">
        <span className="friends__act-ev">{shortTitle(a.event.title)}</span>
        <span className="friends__act-meta">
          <span className="friends__act-who">{who}</span> сохранил · {timeAgo(a.at)}
        </span>
      </span>
      <span
        className={`friends__act-cover${cover ? "" : " friends__act-cover--ph"}`}
        style={cover ? { backgroundImage: `url("${cover}")` } : undefined}
        aria-hidden="true"
      />
    </button>
  );
}

function FriendsSavedBlock({ activity, onSelect }: { activity: FriendActivity[]; onSelect: (i: EventItem) => void }) {
  if (!activity.length) return null;
  return (
    <section className="rail">
      <div className="rail__head">
        <span className="rail__title">Друзья сохранили</span>
      </div>
      <div className="friends__feed">
        {activity.slice(0, 4).map((a, i) => (
          <FriendActivityRow key={`${a.friend.id}-${a.event.event_id}-${i}`} a={a} onOpen={onSelect} />
        ))}
      </div>
    </section>
  );
}

function VenueRowsBlock({
  venues,
  onOpenVenue,
}: {
  venues: VenueDetail[];
  onOpenVenue: (venueId: number) => void;
}) {
  if (!venues.length) return null;
  const hasNew = venues.some((v) => (v.new_count ?? 0) > 0);
  return (
    <section className="rail">
      <div className="rail__head">
        <span className="rail__title">{hasNew ? "Новое на ваших площадках" : "На ваших площадках"}</span>
      </div>
      {venues.slice(0, 4).map((v) => {
        const next = v.events[0] ?? null;
        const cat = next ? categoryMeta(next.category) : null;
        return (
          <button key={v.venue_id} type="button" className="vrow" onClick={() => onOpenVenue(v.venue_id)}>
            <span className="vrow__body">
              <span className="vrow__top">
                <span className="vrow__name">{v.name}</span>
                {(v.new_count ?? 0) > 0 && <span className="vrow__new">+{v.new_count} новых</span>}
              </span>
              {next ? (
                <>
                  <span className="vrow__next">
                    {cat && (
                      <span className="vrow__cat" style={{ "--cat": cat.color } as CSSProperties}>
                        <CategoryIcon cat={next.category} size={13} className="vrow__caticon" />
                        {cat.label}
                      </span>
                    )}
                    <span className="vrow__nexttitle">{next.title}</span>
                  </span>
                  <span className="vrow__nextdate">{formatWhenShort(next.date_start, next.date_end)}</span>
                </>
              ) : (
                <span className="vrow__next">
                  <span className="vrow__addr">{v.address || "Площадка"}</span>
                </span>
              )}
            </span>
            {v.events.length > 0 && (
              <span className="vrow__count">
                <b className="vrow__num">{v.events.length}</b>
                <span className="vrow__numlabel">{plural(v.events.length, "событие", "события", "событий")}</span>
              </span>
            )}
          </button>
        );
      })}
    </section>
  );
}

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
  favIds,
  venueIds,
  refreshNonce = 0,
  city = null,
  onSelect,
  onOpenVenue,
  onOpenCollection,
  onPickCategory,
  onAllCategories,
  onClose,
}: {
  userPos?: LatLon | null;
  favCategories?: string[];
  favIds?: Set<string>;
  venueIds?: Set<string>;
  refreshNonce?: number;
  city?: string | null;
  onSelect: (i: EventItem) => void;
  onOpenVenue: (venueId: number) => void;
  onOpenCollection: (slug: string, title: string, subtitle: string | null) => void;
  onPickCategory: (category: string) => void;
  onAllCategories: () => void;
  onClose: () => void;
}) {
  const [rails, setRails] = useState<Rail[]>([]);
  const [collections, setCollections] = useState<Rail[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [friendsActivity, setFriendsActivity] = useState<FriendActivity[]>([]);
  const [savedSoon, setSavedSoon] = useState<EventItem[]>([]);
  const [followedVenues, setFollowedVenues] = useState<VenueDetail[]>([]);
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

  useEffect(() => {
    let alive = true;
    fetchFriendsActivity().then((a) => {
      if (alive && a) setFriendsActivity(a);
    });
    return () => {
      alive = false;
    };
  }, [refreshNonce, localNonce]);

  const favIdsKey = useMemo(() => [...(favIds ?? new Set<string>())].sort().join(","), [favIds]);
  useEffect(() => {
    const ids = favIdsKey ? favIdsKey.split(",").slice(0, 80) : [];
    if (!ids.length) {
      setSavedSoon([]);
      return;
    }
    const ctrl = new AbortController();
    fetchEventsByIds(ids, userPos ?? null, ctrl.signal).then((items) => {
      const now = Date.now();
      setSavedSoon(
        items
          .filter((it) => Date.parse(it.date_start) >= now)
          .sort((a, b) => Date.parse(a.date_start) - Date.parse(b.date_start))
          .slice(0, 12),
      );
    });
    return () => ctrl.abort();
  }, [favIdsKey, lat, lon, userPos]);

  const venueIdsKey = useMemo(() => [...(venueIds ?? new Set<string>())].sort().join(","), [venueIds]);
  useEffect(() => {
    const ids = venueIdsKey ? venueIdsKey.split(",").slice(0, 8) : [];
    if (!ids.length) {
      setFollowedVenues([]);
      return;
    }
    let seenAt: string | undefined;
    try {
      seenAt = localStorage.getItem("okrest_venues_seen") || undefined;
    } catch {
      /* ignore */
    }
    const ctrl = new AbortController();
    Promise.all(ids.map((id) => fetchVenue(id, ctrl.signal, seenAt).catch(() => null))).then((res) => {
      setFollowedVenues(
        res
          .filter((v): v is VenueDetail => !!v)
          .filter((v) => v.events.length > 0)
          .sort((a, b) => (b.new_count ?? 0) - (a.new_count ?? 0)),
      );
    });
    return () => ctrl.abort();
  }, [venueIdsKey, refreshNonce, localNonce]);

  const hasContent = rails.length > 0 || collections.length > 0;
  const empty = !loading && !error && !hasContent;
  // The first collection (Свидание — always present) gets a featured card rail; the rest become
  // the «Подборки» grid of entry tiles.
  const featured = collections[0] ?? null;
  const gridCollections = collections.slice(1);
  const weekendRail = rails.find((r) => r.key === "weekend") ?? null;
  const otherRails = rails.slice(1).filter((r) => r.key !== "weekend");
  const savedRail: Rail | null = savedSoon.length
    ? { key: "saved_soon", title: "Вы сохранили, скоро начнется", subtitle: "чтобы не забыть", items: savedSoon }
    : null;

  return (
    <div className="panelview">
      <header className="panelview__head">
        <h2>главная</h2>
        <button type="button" className="panelview__close" aria-label="Закрыть" onClick={onClose}>
          <IconClose size={18} />
        </button>
      </header>
      <div className="panelview__scroll panelview__scroll--rails" ref={ptr.ref}>
        <PullHint pull={ptr.pull} armed={ptr.armed} refreshing={loading} />
        {loading && rails.length === 0 && <RailSkeleton />}
        {error && (
          <div className="favempty">
            <p className="panelview__hint">Не удалось загрузить главную. Попробуй ещё раз.</p>
            <button type="button" className="btn btn--primary" onClick={retry}>
              Повторить
            </button>
          </div>
        )}
        {empty && <p className="panelview__empty">пока нечего показать</p>}

        {/* 1) Personal hero. */}
        {rails[0] && <RecRail key={rails[0].key} rail={rails[0]} userPos={userPos} onSelect={onSelect} />}
        <FriendsSavedBlock activity={friendsActivity} onSelect={onSelect} />
        <VenueRowsBlock venues={followedVenues} onOpenVenue={onOpenVenue} />
        {savedRail && <RecRail key={savedRail.key} rail={savedRail} userPos={userPos} onSelect={onSelect} />}
        {weekendRail && <RecRail key={weekendRail.key} rail={weekendRail} userPos={userPos} onSelect={onSelect} />}

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
        {otherRails.map((rail) => (
          <RecRail key={rail.key} rail={rail} userPos={userPos} onSelect={onSelect} />
        ))}
      </div>
    </div>
  );
}
