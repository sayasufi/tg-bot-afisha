import { lazy, Suspense, useCallback, useEffect, useMemo, useRef, useState } from "react";

import { fetchEventDetail, fetchEventsByIds, fetchMapEvents, fetchMetro, type EventItem, type MapCluster, type MetroStation } from "../api/client";
import { logEventSeen } from "../api/recommend";
import { markInvited } from "../api/users";
import { recordOpen, recordViewed } from "../lib/affinity";
import { EMPTY_FILTERS, Filters, type FilterState } from "../features/filters/Filters";
import { ClusterPeek } from "../features/map/ClusterPeek";

// The map pulls in maplibre-gl (~1 MB) + leaflet; lazy-load it so the app shell
// and the instant splash render without waiting on that bundle to parse.
const EventsMap = lazy(() => import("../features/map/EventsMap").then((m) => ({ default: m.EventsMap })));
import { FocusBar } from "../features/map/FocusBar";
import { Coach, EmptyState, LoadingBar, MapShimmer, RadarPing } from "../features/map/MapOverlays";
import { ListView, Sidebar, type View } from "../features/panel";
// View-panels are only mounted when their tab is opened (most users never do) — lazy-load
// so they don't sit in the initial bundle.
const RecommendationsPanel = lazy(() =>
  import("../features/panel/RecommendationsPanel").then((m) => ({ default: m.RecommendationsPanel })),
);
const CollectionDetail = lazy(() =>
  import("../features/panel/CollectionDetail").then((m) => ({ default: m.CollectionDetail })),
);
const FavoritesPanel = lazy(() => import("../features/panel/FavoritesPanel").then((m) => ({ default: m.FavoritesPanel })));
const ProfilePanel = lazy(() => import("../features/panel/ProfilePanel").then((m) => ({ default: m.ProfilePanel })));
const FollowedVenuesPanel = lazy(() =>
  import("../features/panel/FollowedVenuesPanel").then((m) => ({ default: m.FollowedVenuesPanel })),
);
const FriendsPanel = lazy(() => import("../features/panel/FriendsPanel").then((m) => ({ default: m.FriendsPanel })));
const FriendProfile = lazy(() => import("../features/panel/FriendProfile").then((m) => ({ default: m.FriendProfile })));
import { FriendDisclosure } from "../features/panel/FriendDisclosure";
import { FriendInviteAccept } from "../features/panel/FriendInviteAccept";
import { bootstrap, fetchFriendsFavorited, manageFriends, type Friend } from "../api/users";
import { showToast } from "../lib/toast";
import { IconList } from "../lib/icons";
import { Onboarding } from "../features/onboarding/Onboarding";
import { OfflineBanner } from "../features/offline/OfflineBanner";
import { Toaster } from "../features/toast/Toaster";
import { VenueSheet } from "../features/venue/VenueSheet";
import { ProofFrame, Ticker } from "../features/proof/Proof";
import { EventSheet } from "../features/sheet/EventSheet";
import { categoryMeta } from "../lib/categories";
import { rangeFor } from "../lib/datePresets";
import { goNowState, setCityTimezone } from "../lib/datetime";
import { distanceMeters, nearestOf } from "../lib/distance";
import { beginFavoritesAdopt, syncFavorites, useFavorites } from "../lib/favorites";
import { beginVenueFollowsAdopt, syncVenueFollows, useVenueFollows } from "../lib/venueFollows";
import { applyTheme, getUser, getWebApp, haptic, hapticNotify, initTelegram, type ThemeName } from "../lib/telegram";
import { SearchOverlay } from "../features/search/SearchOverlay";
import { loadSettings, pushSetting, type Settings } from "../lib/settings";
import { useCities } from "../lib/useCities";
import { useGeolocation } from "../lib/useGeolocation";

const CITY = "Москва";

// At/below this zoom the map shows server-aggregated clusters instead of pins.
// Keep in sync with DETAIL_ZOOM in EventsMap / _DETAIL_ZOOM in the API service.
const DETAIL_ZOOM = 14;

export function App() {
  const [theme, setTheme] = useState<ThemeName>(() => initTelegram()); // applies saved theme once
  const [tgUser] = useState(() => getUser());
  const fav = useFavorites();
  const venueFollows = useVenueFollows(); // followed-venue count → badge on the «Площадки» nav item
  // Who invited me here (from a share deep-link «<event>_<inviter>_<sig>») — drives the invite banner.
  const [invite, setInvite] = useState<{ eventId: string; inviterId: number; sig: string } | null>(null);
  const [friendInvite, setFriendInvite] = useState<{ inviterId: number; sig: string } | null>(null); // «add me» link
  const [filters, setFilters] = useState<FilterState>(EMPTY_FILTERS);
  const [items, setItems] = useState<EventItem[]>([]);
  const [total, setTotal] = useState(0);
  const [clusters, setClusters] = useState<MapCluster[]>([]);
  const [zoom, setZoom] = useState<number | null>(null);
  // Warmed cluster payloads keyed by request params (filters + zoom), so changing
  // zoom swaps clusters synchronously from memory instead of waiting on the network.
  const clusterCache = useRef<Map<string, MapCluster[]>>(new Map());
  const [metro, setMetro] = useState<MetroStation[]>([]);
  const [selected, setSelected] = useState<EventItem | null>(null);
  // The marker that stays highlighted (acid) on the map — persists after the sheet
  // closes and at any zoom, until you focus another event. `focusOut` plays the
  // dismiss animation before it's actually cleared.
  const [focused, setFocused] = useState<EventItem | null>(null);
  const [focusOut, setFocusOut] = useState(false);
  const focusedRef = useRef<EventItem | null>(null);
  focusedRef.current = focused;
  const [peek, setPeek] = useState<EventItem[] | null>(null);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [filtersOpen, setFiltersOpen] = useState(false);
  const [searchOpen, setSearchOpen] = useState(false);
  // The venue page (opened by tapping the place in an event sheet); holds the venue id.
  const [venueId, setVenueId] = useState<number | null>(null);
  // List view ("Списком"): the current map bbox (reported by EventsMap) + the bbox
  // frozen when the list was opened, so the list reflects the area you were looking at.
  const [mapBbox, setMapBbox] = useState<[number, number, number, number] | null>(null);
  const [mapZoom, setMapZoom] = useState<number | null>(null);
  const [listOpen, setListOpen] = useState(false);
  const [listBbox, setListBbox] = useState<[number, number, number, number] | null>(null);
  // An open «Подборка» detail (opened from the recs grid/«смотреть все»), layered over the recs panel.
  const [collection, setCollection] = useState<{ slug: string; title: string; subtitle: string | null } | null>(null);
  const [view, setView] = useState<View>("map");
  const [sheetReady, setSheetReady] = useState(false);
  const [loading, setLoading] = useState(true);
  // A failed map fetch (server/network), distinct from a genuinely empty result — drives a
  // retry overlay instead of the "Тишина в зале" empty card.
  const [mapError, setMapError] = useState(false);
  const [radarNonce, setRadarNonce] = useState(0);
  const [refreshNonce, setRefreshNonce] = useState(0);
  const [coachSeen, setCoachSeen] = useState(() => {
    try {
      return localStorage.getItem("okrest_coach") === "1";
    } catch {
      return true;
    }
  });
  // First-run guide — shown once over the loaded map (default true on storage failure
  // so it never blocks).
  const [onboarded, setOnboarded] = useState(() => {
    try {
      return localStorage.getItem("okrest_onboarded") === "1";
    } catch {
      return true;
    }
  });
  // Categories the user picked at onboarding — warms «Для тебя» from cold (merged with the
  // favourite-derived categories below). Hydrated from the account on load.
  const [pickedInterests, setPickedInterests] = useState<string[]>([]);
  // Reminder DMs — default ON (the per-event bell is the consent); this is a global mute.
  const [notifyReminders, setNotifyReminders] = useState(true);
  const toggleReminders = useCallback((on: boolean) => {
    setNotifyReminders(on);
    pushSetting("notify_reminders", on);
  }, []);
  // Weekly digest (the bot DMs a Friday roundup) — now OPT-OUT (default on); hydrated from the
  // account on load, toggled off from the profile.
  const [notifyDigest, setNotifyDigest] = useState(true);
  const toggleDigest = useCallback((on: boolean) => {
    setNotifyDigest(on);
    pushSetting("notify_digest", on);
  }, []);
  // Friends privacy: hide ALL my favourites from friends (default off — the friend edge is consent).
  const [friendsPrivate, setFriendsPrivate] = useState(false);
  const toggleFriendsPrivate = useCallback((on: boolean) => {
    setFriendsPrivate(on);
    pushSetting("friends_private", on);
  }, []);
  // First-friend disclosure (fires here when a mutual invite makes you friends instantly) + the menu
  // badge count of incoming friend requests (pulled once on open, kept live by the Friends panel).
  const [friendDisclosure, setFriendDisclosure] = useState(false);
  const [friendCount, setFriendCount] = useState(0); // total accepted friends → badge on «Друзья»
  const [friendProfile, setFriendProfile] = useState<Friend | null>(null); // open friend's profile overlay
  const [friendCounts, setFriendCounts] = useState<Map<string, number>>(() => new Map()); // event_id → #friends who saved it
  // Slim-index map: the per-event payload carries only id/coords/category/dates/price. The heavy fields
  // (title/venue/code/image) are HYDRATED in-frame by id (POST /events/by-ids) into this map; openEvent /
  // the cluster peek / SimilarEvents read full fields from here, with a graceful detail-fetch fallback.
  const [hydrated, setHydrated] = useState<Map<string, EventItem>>(() => new Map());
  const hydratedRef = useRef(hydrated);
  useEffect(() => {
    hydratedRef.current = hydrated;
  }, [hydrated]);
  const { userPos, heading, locating, locateNonce, onLocate } = useGeolocation();
  // Current city (nearest by geolocation, or an explicit pick) drives the map `city`
  // scope param and the map centre — no hardcoded city on the client. The switcher shows
  // only when more than one city is active.
  const { cities, current: currentCity, settingsCity, select: selectCity, view: viewCity, seed: seedCity } = useCities(userPos);
  // Render every event time in the ACTIVE city's wall-clock (Novosibirsk +7 ≠ Moscow +3), not a
  // fixed Moscow offset. datetime.ts holds a module-level offset; flip it whenever the city changes.
  useEffect(() => {
    setCityTimezone(currentCity?.utc_offset ?? 3);
  }, [currentCity?.utc_offset]);
  // If the user changes theme/city before the settings GET resolves, don't let the (older)
  // account value snap it back. Set when they act; checked when the load lands.
  const settingsTouched = useRef({ theme: false, city: false });
  // Persisted city pick — ONLY from the profile. Marks the city touched (so a late settings GET can't
  // revert it) then writes it (local + account). The map's picks are transient (viewCity) and never land here.
  const pickCity = useCallback((slug: string) => {
    settingsTouched.current.city = true;
    selectCity(slug);
  }, [selectCity]);
  // ONE round-trip on open: /bootstrap pulls settings + favourites + venue follows + friend count together
  // (was 4 separate authed POSTs racing the map fetch for the browser's ~6 connections, each re-validating
  // initData). Settings/favourites override this device's local cache when the account has a saved value.
  // On ANY failure we fall back to the 4 independent loads, so the open can never be worse than before.
  useEffect(() => {
    const applyFriends = (count: number) => {
      setFriendCount(count);
      // You may have become someone's friend while away (they accepted your invite). Show the one-time
      // «friends see your saves» disclosure on open if you have any friend and haven't seen it.
      if (count > 0) {
        try {
          if (localStorage.getItem("okrest_friend_disclosed") !== "1") {
            localStorage.setItem("okrest_friend_disclosed", "1");
            setFriendDisclosure(true);
          }
        } catch {
          /* ignore */
        }
      }
    };
    const applySettings = (s: Settings) => {
      if (!settingsTouched.current.theme && (s.theme === "dark" || s.theme === "light")) {
        applyTheme(s.theme);
        setTheme(s.theme);
      }
      if (!settingsTouched.current.city && typeof s.city === "string" && s.city) seedCity(s.city);
      // First-run flags are sticky-true across devices: adopt the account's "seen", and
      // push this device's local "seen" up once so other devices skip it too.
      const reconcile = (lsKey: string, key: "onboarded" | "coach" | "swipe_seen", seen: boolean | undefined, markSeen?: () => void) => {
        let local = false;
        try {
          local = localStorage.getItem(lsKey) === "1";
        } catch {
          /* ignore */
        }
        if (seen) {
          try {
            localStorage.setItem(lsKey, "1");
          } catch {
            /* ignore */
          }
          markSeen?.();
        } else if (local) {
          pushSetting(key, true);
        }
      };
      reconcile("okrest_onboarded", "onboarded", s.onboarded, () => setOnboarded(true));
      reconcile("okrest_coach", "coach", s.coach, () => setCoachSeen(true));
      reconcile("okrest_swipe_seen", "swipe_seen", s.swipe_seen);
      if (Array.isArray(s.interests) && s.interests.length) setPickedInterests(s.interests);
      if (typeof s.notify_reminders === "boolean") setNotifyReminders(s.notify_reminders);
      if (typeof s.notify_digest === "boolean") setNotifyDigest(s.notify_digest);
      if (typeof s.friends_private === "boolean") setFriendsPrivate(s.friends_private);
    };
    // Capture the favourites/venues merge-payload + mutation seq BEFORE the request (so a toggle made
    // mid-flight can't be clobbered by the stale server list) — same guards the per-store syncs use.
    const favAdopt = beginFavoritesAdopt();
    const venueAdopt = beginVenueFollowsAdopt();
    void bootstrap(favAdopt.add).then((b) => {
      if (b) {
        favAdopt.adopt(b.favorite_ids);
        venueAdopt(b.venue_follow_ids);
        if (b.settings) applySettings(b.settings);
        applyFriends(b.friends_count);
      } else {
        // Couldn't bootstrap (offline / non-Telegram / error) — fall back to the independent loads.
        void syncFavorites();
        void syncVenueFollows();
        void manageFriends().then((s) => s && applyFriends(s.friends.length));
        void loadSettings().then((s) => s && applySettings(s));
      }
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // A coarse clock that ticks once a minute — drives the "можно пойти сейчас"
  // set (countdowns, which events are still catchable) without re-rendering the
  // map on every frame. One minute is plenty: the window is hours, labels are in
  // minutes.
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    // Pause the tick while backgrounded — no point re-rendering + re-scanning goNow over
    // the whole set when the app isn't visible; refresh immediately on return.
    let t: ReturnType<typeof setInterval> | undefined;
    const start = () => {
      if (t === undefined && !document.hidden) t = setInterval(() => setNow(Date.now()), 60_000);
    };
    const stop = () => {
      if (t !== undefined) {
        clearInterval(t);
        t = undefined;
      }
    };
    const onVis = () => {
      if (document.hidden) stop();
      else {
        setNow(Date.now());
        start();
      }
    };
    start();
    document.addEventListener("visibilitychange", onVis);
    return () => {
      stop();
      document.removeEventListener("visibilitychange", onVis);
    };
  }, []);

  const query = useMemo(() => {
    const params = new URLSearchParams();
    // No limit: fetch every event matching the filters so the map shows exactly the
    // "Показать N" count (and the client-side radius filter works over the full set).
    // Rendering is optimised by clustering (react-leaflet-cluster + chunkedLoading),
    // which keeps thousands of markers smooth without capping the data.
    if (filters.q) params.set("q", filters.q);
    for (const c of filters.categories) params.append("categories", c);
    // Span the WHOLE Moscow day. The dates are Moscow-anchored (see datePresets), so
    // pin the bounds to Moscow's UTC+3 — NOT the client's tz. `new Date("…T00:00:00")`
    // alone parses in the device timezone, which shifts the window by hours for any
    // non-MSK client and drops/adds a band of events. (All current cities are UTC+3,
    // no DST since 2014; generalise per-city tz when a non-UTC+3 city goes live.)
    if (filters.dateFrom) params.set("date_from", new Date(`${filters.dateFrom}T00:00:00+03:00`).toISOString());
    if (filters.dateTo) params.set("date_to", new Date(`${filters.dateTo}T23:59:59+03:00`).toISOString());
    if (filters.priceMax) params.set("price_max", filters.priceMax);
    // Scope the map to the current city (multi-city). Absent until /v1/cities resolves;
    // the server treats "no city" as all-active, so the first frame is still correct.
    if (currentCity) params.set("city", currentCity.slug);
    return params;
  }, [filters, currentCity?.slug]);
  // Stable string of the server-affecting params — the map/cluster fetches key on this so a
  // client-only filter change (radius, "Сейчас") rebuilds `query` but never refetches.
  const queryKey = query.toString();

  // Distance filter ("Рядом") is applied client-side over the fetched set, so
  // the radius slider responds instantly without a round-trip.
  const radiusItems = useMemo(() => {
    if (!filters.radiusKm || !userPos) return items;
    const limit = filters.radiusKm * 1000;
    return items.filter((i) => i.lat != null && i.lon != null && distanceMeters(userPos, [i.lat, i.lon]) <= limit);
  }, [items, filters.radiusKm, userPos]);

  // "Можно пойти сейчас": the event_ids you can realistically still go to right
  // now — timed events starting within the next 3 hours (not yet begun), plus
  // ongoing venues open at this moment. Computed ONCE here and reused by the
  // filter, the ticker count and the map highlight, so the three can never
  // disagree at a minute boundary.
  const goNowIds = useMemo(() => {
    const at = new Date(now);
    const ids = new Set<string>();
    for (const i of radiusItems) {
      if (goNowState(i.date_start, i.date_end, i.open_now, at).eligible) ids.add(i.event_id);
    }
    return ids;
  }, [radiusItems, now]);

  const shownItems = useMemo(
    () => (filters.goNow ? radiusItems.filter((i) => goNowIds.has(i.event_id)) : radiusItems),
    [radiusItems, filters.goNow, goNowIds],
  );

  // Friends-on-map: which of the visible events a friend has saved → an acid ring on those pins. Only
  // at detail zoom (individual pins, a neighbourhood-sized set), debounced so panning doesn't spam the
  // user-scoped side-channel. NOT gated on a cached «has friends» flag — that goes stale the moment you
  // become a friend mid-session (the bug); a friendless user's query is empty + cheap (0-row JOIN).
  useEffect(() => {
    const bb = mapBbox;
    if (view !== "map" || (mapZoom ?? 0) < DETAIL_ZOOM || shownItems.length === 0) {
      setFriendCounts((prev) => (prev.size ? new Map() : prev));
      return;
    }
    // Send the events actually IN VIEW, not the first 250 of every loaded event — shownItems accumulates
    // far more than the viewport, so the visible (rendered) pins could fall past the cap and never be
    // checked. Filter to mapBbox (same bbox the map renders pins for) so the visible set is what we ask.
    const inView = bb
      ? shownItems.filter((i) => i.lat != null && i.lon != null && i.lon >= bb[0] && i.lon <= bb[2] && i.lat >= bb[1] && i.lat <= bb[3])
      : shownItems;
    if (inView.length === 0) {
      setFriendCounts((prev) => (prev.size ? new Map() : prev));
      return;
    }
    const ids = inView.slice(0, 250).map((i) => i.event_id);
    let alive = true;
    const t = setTimeout(() => {
      void fetchFriendsFavorited(ids).then((res) => {
        if (!alive || !res) return;
        const keys = Object.keys(res.friends);
        // Keep the SAME Map identity when nothing changed (same events AND same counts) — otherwise a new
        // equal reference would re-trigger the pins memo and rebuild every marker after each zoom/pan.
        setFriendCounts((prev) =>
          prev.size === keys.length && keys.every((k) => prev.get(k) === res.friends[k].length)
            ? prev
            : new Map(keys.map((k) => [k, res.friends[k].length])),
        );
      });
    }, 450);
    return () => {
      alive = false;
      clearTimeout(t);
    };
  }, [view, mapZoom, mapBbox, shownItems]);

  // Hydrate the heavy per-event fields (title/venue/code/image) for the events IN VIEW at detail zoom, so a
  // tapped pin / the cluster peek / SimilarEvents have full data instantly (the slim index payload omits
  // them). Debounced, fetches ONLY ids not already hydrated (panning reuses what we have), no position so
  // the by-ids result is shareable/cacheable. A not-yet-hydrated tap still works — the sheet falls back to
  // its detail fetch for the title.
  useEffect(() => {
    const bb = mapBbox;
    if (view !== "map" || (mapZoom ?? 0) < DETAIL_ZOOM || shownItems.length === 0) return;
    const inView = bb
      ? shownItems.filter((i) => i.lat != null && i.lon != null && i.lon >= bb[0] && i.lon <= bb[2] && i.lat >= bb[1] && i.lat <= bb[3])
      : shownItems;
    const need = inView.slice(0, 250).filter((i) => !hydratedRef.current.has(i.event_id)).map((i) => i.event_id);
    if (need.length === 0) return;
    let alive = true;
    const t = setTimeout(() => {
      void fetchEventsByIds(need).then((full) => {
        if (!alive || full.length === 0) return;
        setHydrated((prev) => {
          const next = new Map(prev);
          for (const e of full) next.set(e.event_id, e);
          return next.size > 1500 ? new Map([...next].slice(-900)) : next; // bound memory on long pans
        });
      });
    }, 400);
    return () => {
      alive = false;
      clearTimeout(t);
    };
  }, [view, mapZoom, mapBbox, shownItems]);
  const shownTotal = (filters.radiusKm && userPos) || filters.goNow ? shownItems.length : total;
  // Slim items enriched with hydrated full fields — for the sheet's «похожие» strip (the map pins +
  // clustering keep the lean index set; only consumers that show titles/thumbs need the rich version).
  const displayItems = useMemo(
    () =>
      hydrated.size
        ? shownItems.map((it) => {
            const h = hydrated.get(it.event_id);
            return h ? { ...it, ...h } : it;
          })
        : shownItems,
    [shownItems, hydrated],
  );

  // «Сейчас» list header count: the can-go-now events (the same map pins, via goNowIds) that
  // fall inside the list's frozen bbox. We compute the FULL total here up front — the list's own
  // client-side goNow filter only sees the pages loaded so far, so its count would otherwise creep
  // up as you scroll. Deriving it from goNowIds also keeps the list header and the map in agreement.
  // bbox = [minLon, minLat, maxLon, maxLat], matching the server's ST_MakeEnvelope (inclusive).
  const listLiveTotal = useMemo(() => {
    if (!filters.goNow || !listBbox) return 0;
    const [w, s, e, n] = listBbox;
    let c = 0;
    for (const it of shownItems) {
      if (it.lat == null || it.lon == null) continue;
      if (it.lon >= w && it.lon <= e && it.lat >= s && it.lat <= n) c++;
    }
    return c;
  }, [shownItems, listBbox, filters.goNow]);

  // Server clustering is used unless a client-side set is in play (radius or
  // "можно пойти") — those sets are small and filtered client-side, so we pin
  // them directly instead of asking the server to grid them.
  const clusterMode = !((filters.radiusKm > 0 && !!userPos) || filters.goNow);
  // Only the integer zoom drives clustering; the map reports it on zoomend.
  const onZoom = useCallback((z: number) => {
    setZoom(z);
  }, []);

  // Favourite categories drive the "Для тебя" boost in recommendations.
  const favCategories = useMemo(() => {
    const counts = new Map<string, number>();
    for (const it of items) if (fav.ids.has(it.event_id)) counts.set(it.category, (counts.get(it.category) || 0) + 1);
    return [...counts.entries()].sort((a, b) => b[1] - a[1]).map(([k]) => k);
  }, [items, fav.ids]);

  // The affinity that feeds «Для тебя»: favourite-derived categories + the onboarding
  // picks, de-duped. The picks warm a brand-new account; favourites refine it over time.
  const recInterests = useMemo(
    () => [...new Set([...favCategories, ...pickedInterests])],
    [favCategories, pickedInterests],
  );

  // Nearest metro to the open event — shown in the sheet and pinged on the map.
  const nearMetro = useMemo(() => {
    if (!selected || selected.lat == null || selected.lon == null || metro.length === 0) return null;
    const hit = nearestOf([selected.lat, selected.lon], metro);
    return hit ? { ...hit.item, meters: hit.meters } : null;
  }, [selected, metro]);

  // How many events you can still get to right now — drives the ticker's pulse.
  // Same Set the filter and the map highlight use, so the counts never diverge.
  const liveCount = goNowIds.size;

  // Gallery ticker line: total + city + can-go-now + the busiest categories.
  const tickerText = useMemo(() => {
    // Far-zoom city picker (zoom <= 6): one city's category counts are out of context — show the country-wide
    // line instead (matches the picker caption), so the ticker can't contradict "21 087 событий".
    if ((zoom ?? 99) <= 6 && cities.length > 1) {
      const countryTotal = cities.reduce((s, c) => s + c.count, 0);
      return [`${countryTotal.toLocaleString("ru-RU")} СОБЫТИЙ`, `${cities.length} ГОРОДОВ`, "ВСЯ РОССИЯ", "ОКРЕСТ"].join(" ● ");
    }
    const segs = [`${shownTotal} СОБЫТИЙ`, (currentCity?.name ?? "Город").toUpperCase(), "ОКРЕСТ"];
    if (liveCount > 0) segs.push(`МОЖНО ПОЙТИ ${liveCount}`);
    const counts: Record<string, number> = {};
    for (const it of shownItems) counts[it.category] = (counts[it.category] || 0) + 1;
    Object.entries(counts)
      .sort((a, b) => b[1] - a[1])
      .slice(0, 3)
      .forEach(([k, n]) => segs.push(`${categoryMeta(k).label.toUpperCase()} ${n}`));
    return segs.join(" ● ");
  }, [shownItems, shownTotal, liveCount, currentCity?.name, zoom, cities]);

  // Load metro stations (for the nearest-station label + map ping). Only Moscow has a baked
  // metro layer for now, so other cities get an empty set — no wrong Moscow station on a SPb
  // event. Re-runs on city switch.
  useEffect(() => {
    if ((currentCity?.slug ?? "moscow") !== "moscow") {
      setMetro([]);
      return;
    }
    const ctrl = new AbortController();
    fetchMetro(ctrl.signal)
      .then(setMetro)
      .catch(() => undefined);
    return () => ctrl.abort();
  }, [currentCity?.slug]);

  // Fetch the whole city's pins ONCE per server-scope (categories/dates/price/city) — the
  // payload is gzip+Redis-cached server-side, so every client shares ONE warm cache key
  // (it scales to any number of users). Panning, zooming and the client-side view filters
  // (Рядом / Сейчас) then operate over this set with NO further round-trips: the map only
  // instantiates markers inside the viewport (EventsMap culls), so a city-wide set costs
  // nothing extra to render. Keyed on the query STRING, so toggling a client-only filter
  // (which doesn't change a server param) never refetches.
  useEffect(() => {
    setLoading(true);
    setMapError(false);
    const ctrl = new AbortController();
    const t = setTimeout(() => {
      fetchMapEvents(new URLSearchParams(query), ctrl.signal)
        .then((res) => {
          setItems(res.items);
          setTotal(res.total);
          setLoading(false);
          if (refreshNonce > 0) hapticNotify("success");
        })
        .catch((e) => {
          if (e?.name !== "AbortError") {
            // A failed fetch is NOT an empty map — flag the error so we show a retry,
            // not the "Тишина в зале" empty card.
            setItems([]);
            setTotal(0);
            setLoading(false);
            setMapError(true);
          }
        });
    }, 280);
    return () => {
      clearTimeout(t);
      ctrl.abort();
    };
    // refreshNonce forces a re-fetch on pull-to-refresh.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [queryKey, refreshNonce]);

  // Pull-to-refresh invalidates the warmed clusters so they refetch fresh.
  useEffect(() => {
    clusterCache.current.clear();
  }, [refreshNonce]);

  // Current zoom's clusters: served INSTANTLY from the in-memory cache when warm
  // (a synchronous swap, no network/debounce), otherwise fetched once and cached.
  // Keyed on zoom + filters only (not the panning bbox) — clusters are whole-city.
  useEffect(() => {
    if (zoom == null || !clusterMode || zoom >= DETAIL_ZOOM) {
      setClusters([]);
      return;
    }
    const p = new URLSearchParams(query);
    p.set("zoom", String(zoom));
    const key = p.toString();
    const warm = clusterCache.current.get(key);
    if (warm) {
      setClusters(warm);
      return;
    }
    const ctrl = new AbortController();
    const t = setTimeout(() => {
      fetchMapEvents(p, ctrl.signal)
        .then((res) => {
          clusterCache.current.set(key, res.clusters);
          setClusters(res.clusters);
        })
        .catch((e) => {
          if (e?.name !== "AbortError") setClusters([]);
        });
    }, 200);
    return () => {
      clearTimeout(t);
      ctrl.abort();
    };
  }, [zoom, queryKey, clusterMode, refreshNonce]);

  // Prefetch the cluster-zoom band so the FIRST visit to any zoom is already warm → zooming feels
  // instant. CRITICAL: do it ONE AT A TIME and only when the browser is IDLE — the old version fired all
  // ~7 levels in parallel on a 700ms timer, starving the ~6 connection slots on open and delaying the
  // first paint / any tapped tab. Sequential + requestIdleCallback (setTimeout fallback for iOS webview)
  // keeps it strictly background. Tiny payloads, deduped against the cache, served from Redis.
  useEffect(() => {
    if (!clusterMode) return;
    const ctrl = new AbortController();
    let cancelled = false;
    const run = async () => {
      for (let z = 7; z < DETAIL_ZOOM; z++) {
        if (cancelled) return;
        const p = new URLSearchParams(query);
        p.set("zoom", String(z));
        const key = p.toString();
        if (clusterCache.current.has(key)) continue;
        try {
          const res = await fetchMapEvents(p, ctrl.signal);
          clusterCache.current.set(key, res.clusters);
        } catch {
          /* ignore — a cold zoom just fetches on demand */
        }
      }
    };
    const useRic = typeof window.requestIdleCallback === "function";
    const id = useRic
      ? window.requestIdleCallback(() => void run(), { timeout: 2500 })
      : window.setTimeout(() => void run(), 1200);
    return () => {
      cancelled = true;
      ctrl.abort();
      if (useRic && typeof window.cancelIdleCallback === "function") window.cancelIdleCallback(id);
      else clearTimeout(id);
    };
  }, [queryKey, clusterMode, refreshNonce]);

  const dismissOnboarding = useCallback((interests: string[] = []) => {
    haptic("light");
    try {
      localStorage.setItem("okrest_onboarded", "1");
    } catch {
      /* ignore */
    }
    setOnboarded(true);
    pushSetting("onboarded", true); // remember on the account, not just this device
    if (interests.length) {
      setPickedInterests(interests);
      pushSetting("interests", interests); // sync the cold-start taste to the account
    }
  }, []);

  // Close whatever is on top, most-modal first — shared by the Telegram BackButton and
  // the keyboard Escape, so both behave like tapping the visible × . Returns true if it
  // closed something.
  const closeTop = useCallback((): boolean => {
    if (searchOpen) setSearchOpen(false);
    else if (selected) setSelected(null);
    else if (venueId != null) setVenueId(null);
    else if (peek) setPeek(null);
    else if (filtersOpen) setFiltersOpen(false);
    else if (drawerOpen) setDrawerOpen(false);
    else if (listOpen) setListOpen(false);
    else if (collection) setCollection(null); // the «Подборка» detail closes back to the recs panel
    else if (friendInvite) setFriendInvite(null); // the «add me» accept screen
    else if (friendProfile) setFriendProfile(null); // a friend's profile closes back to the Friends list
    else if (view !== "map") setView("map");
    else return false;
    // Drop focus from the trigger so it doesn't keep a focus ring after closing
    // (a keyboard Escape otherwise leaves the pill button looking "highlighted").
    (document.activeElement as HTMLElement | null)?.blur?.();
    return true;
  }, [searchOpen, selected, venueId, peek, filtersOpen, drawerOpen, listOpen, collection, friendInvite, friendProfile, view]);

  // «Подборки» tile / «смотреть все» → the full collection detail (layered over the recs panel).
  const onOpenCollection = useCallback((slug: string, title: string, subtitle: string | null) => {
    haptic("light");
    setCollection({ slug, title, subtitle });
  }, []);
  // «По интересам» → close the recs panel and show the map filtered to the tapped category.
  const onPickCategory = useCallback((category: string) => {
    haptic("light");
    setCollection(null);
    setFilters({ ...EMPTY_FILTERS, categories: [category] });
    setView("map");
  }, []);
  // «ещё» / «все категории» → the map with the filter sheet open, to pick any category.
  const onAllCategories = useCallback(() => {
    haptic("light");
    setCollection(null);
    setView("map");
    setFiltersOpen(true);
  }, []);

  // Telegram back button closes whatever is on top (search → sheet → peek → filters →
  // drawer → panel).
  useEffect(() => {
    const back = getWebApp()?.BackButton;
    if (!back) return;
    const stacked = selected || venueId != null || peek || filtersOpen || drawerOpen || searchOpen || listOpen || collection != null || friendInvite != null || friendProfile != null || view !== "map";
    const pop = () => closeTop();
    if (stacked) {
      back.show();
      back.onClick(pop);
    } else {
      back.hide();
    }
    return () => back.offClick(pop);
  }, [selected, venueId, peek, filtersOpen, drawerOpen, searchOpen, listOpen, collection, friendInvite, friendProfile, view, closeTop]);

  // Esc behaves like tapping the visible × — closes the first-run guide, then the
  // top overlay.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      if (!onboarded) {
        dismissOnboarding();
        (document.activeElement as HTMLElement | null)?.blur?.();
        return;
      }
      closeTop();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onboarded, dismissOnboarding, closeTop]);

  const dismissCoach = useCallback(() => {
    setCoachSeen(true);
    try {
      localStorage.setItem("okrest_coach", "1");
    } catch {
      /* ignore */
    }
    pushSetting("coach", true); // remember on the account, not just this device
  }, []);

  // Auto-dismiss the first-run coach if untouched.
  useEffect(() => {
    if (coachSeen) return;
    const t = setTimeout(dismissCoach, 9000);
    return () => clearTimeout(t);
  }, [coachSeen, dismissCoach]);

  // Locate sequence: the map recenters on locateNonce; once it has settled,
  // give a short buzz and only THEN play the radar rings from the user.
  useEffect(() => {
    if (locateNonce === 0) return;
    const t = setTimeout(() => {
      haptic("medium");
      setRadarNonce((n) => n + 1);
    }, 650);
    return () => clearTimeout(t);
  }, [locateNonce]);

  const openEvent = useCallback((i: EventItem) => {
    haptic("light");
    // A slim-index map pin carries no title/venue/code — overlay the hydrated full event if we have it
    // (in-view set is hydrated by id), MERGING so index-only fields (venue_id) survive; the sheet's detail
    // fetch fills the rest / covers a fresh tap before its hydration landed.
    const h = hydratedRef.current.get(i.event_id);
    const full = h ? { ...i, ...h } : i;
    // Keep the cluster peek behind the sheet ONLY while it still contains this event
    // (so closing returns you to the same point's list + swipe siblings). Opening an
    // event from elsewhere (a "Рядом" card, a different pin) drops the stale peek so it
    // can't reappear out of sync with the map.
    setPeek((p) => (p && p.some((e) => e.event_id === i.event_id) ? p : null));
    setSelected(full);
    setFocused(full); // keep this marker highlighted on the map even after closing
    setFocusOut(false); // cancel any pending dismiss animation
    logEventSeen(i.event_id); // engagement signal for recommendations
    recordOpen(i.category); // behavioural profile for personalised ranking
    recordViewed(i.event_id); // «просмотрено» counter shown in the profile
  }, []);

  // The peek is a map-only overlay: drop it when leaving the map (recs/favorites/
  // profile) so it never lingers behind a panel.
  useEffect(() => {
    if (view !== "map") setPeek(null);
  }, [view]);

  // A friend's profile overlays the Friends view — drop it when we navigate elsewhere (e.g. «На карте»
  // from an event opened inside it) so it can't linger over the map.
  useEffect(() => {
    if (view !== "friends") setFriendProfile(null);
  }, [view]);

  // Hold the event sheet back briefly after a selection so the pin→sheet spark,
  // the camera fly and the constellation play out on the open map before the
  // card rises to cover it. Closing is instant.
  useEffect(() => {
    if (!selected) {
      setSheetReady(false);
      return;
    }
    // Opened from a panel (recs/favorites) → no map choreography to wait for, so
    // the sheet rises immediately over the panel.
    if (view !== "map") {
      setSheetReady(true);
      return;
    }
    const t = setTimeout(() => setSheetReady(true), 560);
    return () => clearTimeout(t);
  }, [selected, view]);

  const onCluster = useCallback((evs: EventItem[]) => {
    haptic("light");
    // The peek rows need title/venue — overlay hydrated full events (in-view → already hydrated), merging
    // so the index-only venue_id survives (the «open this venue» button needs it).
    setPeek(
      evs.map((e) => {
        const h = hydratedRef.current.get(e.event_id);
        return h ? { ...e, ...h } : e;
      }),
    );
  }, []);

  // "На карте" from the sheet: drop to the map (the camera already flew to the
  // event when it was opened) and close everything that covers it so the pin is in view.
  const showOnMap = useCallback(() => {
    haptic("light");
    setView("map"); // closes recs/favorites/profile panels
    setListOpen(false); // the list is a separate overlay — close it too (was the bug)
    setVenueId(null); // the venue page (opened from «Площадки») was left covering the map
    setSearchOpen(false); // and a search overlay would too
    setSelected(null);
    setPeek(null); // "На карте" wants the pin in view, not the peek list over it
  }, []);

  // Tap the venue in an event sheet → open the venue page. Close the event sheet so the
  // venue is the base; tapping one of its events then opens an event sheet on top of it.
  const onOpenVenue = useCallback((vid: number) => {
    haptic("light");
    setSelected(null);
    setPeek(null);
    setVenueId(vid);
  }, []);

  // Dismiss the highlight WITH an exit animation: flag it out, then clear after the
  // animation. Tapping the empty map does the same (only when something is focused).
  const dismissFocus = useCallback(() => {
    haptic("light");
    setFocusOut(true);
  }, []);
  const clearFocus = useCallback(() => {
    if (focusedRef.current) setFocusOut(true);
  }, []);
  useEffect(() => {
    if (!focusOut) return;
    const t = setTimeout(() => {
      setFocused(null);
      setFocusOut(false);
    }, 230);
    return () => clearTimeout(t);
  }, [focusOut]);
  // Zooming out to the city-picker band (zoom <= 6) drops the highlighted marker ENTIRELY — it would
  // otherwise sit on a city dot, and the FocusBar would fight the «Выберите город» banner. Cleared, not hidden.
  useEffect(() => {
    if (zoom != null && zoom <= 6 && focusedRef.current) {
      setFocused(null);
      setFocusOut(false);
    }
  }, [zoom]);

  const handleLocate = useCallback(() => {
    dismissCoach();
    onLocate();
  }, [dismissCoach, onLocate]);
  // The slim "marked exhibit" bar shows on the map when a marker is highlighted
  // and no card is open.
  const focusBarVisible = view === "map" && !!focused && !selected && !peek;

  const onRefresh = useCallback(() => {
    haptic("medium");
    setRefreshNonce((n) => n + 1);
  }, []);

  // Drop the instant splash only once the basemap has actually rendered, so the
  // user never sees a blank/initialising map (and no layout shift behind it).
  const handleMapReady = useCallback(() => {
    const splash = document.getElementById("splash");
    if (!splash || splash.dataset.lifting) return;
    splash.dataset.lifting = "1";
    // Let the first tiles + pins settle behind the splash, then lift — so the
    // user sees a finished map, not the tail of its layout settling.
    window.setTimeout(() => {
      splash.classList.add("hide");
      window.setTimeout(() => splash.remove(), 400);
    }, 300);
  }, []);

  const toggleTheme = useCallback(() => {
    haptic("light");
    settingsTouched.current.theme = true; // user chose — a late settings GET must not revert it
    setTheme((t) => {
      const next: ThemeName = t === "dark" ? "light" : "dark";
      applyTheme(next);
      pushSetting("theme", next); // sync the choice to the account, not this device
      return next;
    });
  }, []);

  // Deep link: open a specific event passed via startapp (?startapp=<id>) or a
  // ?event=<id> query — e.g. when a shared card is tapped.
  useEffect(() => {
    const wa = getWebApp() as any;
    const raw: string | undefined =
      wa?.initDataUnsafe?.start_param || new URLSearchParams(window.location.search).get("event") || undefined;
    if (!raw) return;
    // The Mini App start_param sticks across reloads — without this guard every refresh re-opens
    // the deep-linked event. Open it once per launch: sessionStorage survives reloads but clears on
    // a fresh open, so re-tapping the invite still works.
    try {
      if (sessionStorage.getItem("okrest_deeplink") === raw) return;
      sessionStorage.setItem("okrest_deeplink", raw);
    } catch {
      /* no storage (private mode) — fall through and open as before */
    }
    // A share deep-link may carry the inviter: «<event-uuid>_<inviter-id>_<sig>». The UUID has no
    // '_', so split on '_'. The HMAC sig (minted by our share endpoint) is verified server-side;
    // without a valid one the inviter is ignored (no DM, no taste warm-start) — anti-spoof.
    const parts = raw.split("_");
    const eventId = parts[0];
    const inviterId = parts[1] ? Number(parts[1]) : NaN;
    const inviteSig = parts[2] ?? null;
    // A non-UUID start_param is a KEYWORD route, not an event id (e.g. the weekly digest's
    // «weekend» CTA). Opening it as an event 422s and silently dumps the user on the default map.
    const isUuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(eventId);
    if (!isUuid) {
      if (eventId === "weekend") {
        setFilters((prev) => ({ ...prev, goNow: false, ...rangeFor("weekend") }));
        setView("map");
      } else if (eventId === "friend" && Number.isFinite(inviterId) && inviteSig) {
        setFriendInvite({ inviterId, sig: inviteSig }); // «friend_<id>_<sig>» — show the accept screen
      } else if (eventId === "friends") {
        setView("friends"); // a friend-add DM's «друзья →» button
      }
      return;
    }
    fetchEventDetail(eventId)
      .then((d) => {
        if (Number.isFinite(inviterId) && inviteSig) {
          setInvite({ eventId: d.event_id, inviterId, sig: inviteSig });
          // Referral warm-start: attribute the inviter + warm a still-cold feed from their taste.
          // The server re-verifies the sig, so a forged inviter returns nothing (no warm, no leak).
          void markInvited(eventId, inviterId, inviteSig).then((warm) => {
            if (warm && warm.length) setPickedInterests((prev) => (prev.length ? prev : warm));
          });
        }
        const occ = d.occurrences?.[0];
        openEvent({
          event_id: d.event_id,
          code: d.code,
          title: d.canonical_title,
          category: d.category,
          date_start: occ?.date_start ?? "",
          date_end: occ?.date_end ?? null,
          price_min: occ?.price_min ?? null,
          venue: occ?.venue ?? null,
          lat: occ?.lat ?? null,
          lon: occ?.lon ?? null,
          primary_image_url: d.primary_image_url,
        });
      })
      .catch(() => undefined);
  }, [openEvent]);

  return (
    <div className={`app${focusBarVisible ? " app--focusbar" : ""}`}>
      <Filters
        value={filters}
        total={shownTotal}
        open={filtersOpen}
        hasLocation={!!userPos}
        onOpenChange={setFiltersOpen}
        onChange={setFilters}
        onMenu={() => setDrawerOpen(true)}
        onOpenSearch={() => setSearchOpen(true)}
        favCount={fav.ids.size}
      />
      <SearchOverlay
        open={searchOpen}
        city={currentCity?.slug ?? null}
        userPos={userPos}
        onSelect={openEvent}
        onClose={() => setSearchOpen(false)}
      />
      {view === "map" && !selected && !filtersOpen && (
        <Ticker
          text={tickerText}
          live={liveCount > 0}
          onClick={() => {
            haptic("light");
            setView("recs");
          }}
        />
      )}
      <Suspense fallback={null}>
        <EventsMap
          items={shownItems}
          clusters={clusters}
          clusterMode={clusterMode}
          goNowIds={goNowIds}
          friendCounts={friendCounts}
          selected={selected}
          focused={focused}
          focusOut={focusOut}
          userPos={userPos}
          heading={heading}
          locateNonce={locateNonce}
          theme={theme}
          center={currentCity ? [currentCity.lat, currentCity.lon] : null}
          cities={cities}
          currentCitySlug={currentCity?.slug ?? null}
          onSelectCity={viewCity}
          metro={nearMetro}
          onSelect={openEvent}
          onCluster={onCluster}
          onZoom={onZoom}
          onClearFocus={clearFocus}
          onLocate={handleLocate}
          locating={locating}
          onReady={handleMapReady}
          onViewport={(bbox, zoom) => {
            setMapBbox(bbox);
            setMapZoom(zoom);
          }}
        />
      </Suspense>

      <ClusterPeek events={selected ? null : peek} userPos={userPos} now={now} onSelect={openEvent} onOpenVenue={onOpenVenue} onClose={() => setPeek(null)} />

      <RadarPing key={radarNonce} nonce={radarNonce} />

      <LoadingBar show={loading && view === "map"} />
      <MapShimmer show={loading && items.length === 0 && view === "map" && !selected} />

      {/* A failed fetch shows a retry overlay; a genuinely empty result shows the EmptyState. */}
      {view === "map" && !selected && !filtersOpen && !drawerOpen && !loading && mapError && (
        <div className="emptystate" role="alert">
          <span className="dotfield" aria-hidden="true" />
          <div className="emptystate__card">
            <span className="kicker kicker--code emptystate__kicker">Окрест</span>
            <div className="emptystate__title serif">
              Связь <em>прервалась</em>
            </div>
            <p className="emptystate__text">Не удалось загрузить события. Попробуй ещё раз.</p>
            <button type="button" className="btn btn--primary emptystate__btn" onClick={onRefresh}>
              Повторить
            </button>
          </div>
        </div>
      )}

      {view === "map" && !selected && !filtersOpen && !drawerOpen && !loading && !mapError && shownItems.length === 0 && (
        <EmptyState
          filters={filters}
          radiusActive={!!filters.radiusKm && !!userPos}
          onReset={() => setFilters(EMPTY_FILTERS)}
          onWiden={() => setFilters({ ...filters, radiusKm: 0, categories: [], priceMax: "", goNow: false })}
        />
      )}

      {view === "map" && !selected && !filtersOpen && !drawerOpen && !coachSeen && !userPos && (
        <Coach onDismiss={dismissCoach} />
      )}

      {focusBarVisible && focused && <FocusBar event={focused} out={focusOut} now={now} onOpen={openEvent} onClose={dismissFocus} />}

      {/* Map↔list toggle — opens the current map area as a sortable list. */}
      {view === "map" && !selected && !peek && !filtersOpen && !drawerOpen && !searchOpen && !listOpen && !focusBarVisible && !loading && (
        <button
          type="button"
          className="listfab"
          aria-label="Показать списком"
          onClick={() => {
            haptic("light");
            setListBbox(mapBbox);
            setListOpen(true);
          }}
        >
          <IconList size={20} />
        </button>
      )}

      <ListView
        open={listOpen}
        baseParams={query}
        bbox={listBbox}
        userPos={userPos}
        radiusKm={filters.radiusKm}
        goNow={filters.goNow}
        liveTotal={listLiveTotal}
        now={now}
        onSelect={openEvent}
        onClose={() => setListOpen(false)}
      />

      <EventSheet
        selected={sheetReady ? selected : null}
        query={filters.q}
        userPos={userPos}
        items={displayItems}
        siblings={peek ?? undefined}
        metro={nearMetro}
        isFav={!!selected && fav.has(selected.event_id)}
        onToggleFav={() => selected && fav.toggle(selected.event_id)}
        invitedBy={invite && selected?.event_id === invite.eventId ? invite.inviterId : null}
        onAccept={() => {
          if (!selected) return;
          // Accepting a «Пойдём?» invite = favourite it + attribute the inviter (the bot DMs them) +
          // send a friend REQUEST — or, if you'd each invited the other, become friends instantly.
          const inv = invite && invite.eventId === selected.event_id ? invite : null;
          if (!inv) return;
          void fav.accept(selected.event_id, inv.inviterId, inv.sig).then(({ friend, firstFriend }) => {
            showToast(
              friend === "accepted"
                ? "Теперь вы друзья!"
                : friend === "pending"
                  ? "В избранном · заявка в друзья отправлена"
                  : "Добавлено в избранное",
              { tone: "good" },
            );
            if (firstFriend) {
              try {
                if (localStorage.getItem("okrest_friend_disclosed") !== "1") {
                  localStorage.setItem("okrest_friend_disclosed", "1");
                  setFriendDisclosure(true);
                }
              } catch {
                /* ignore */
              }
            }
          });
        }}
        onSelect={openEvent}
        onShowMap={showOnMap}
        onOpenVenue={onOpenVenue}
        onClose={() => setSelected(null)}
      />

      {venueId != null && (
        <VenueSheet venueId={venueId} userPos={userPos} now={now} onSelect={openEvent} onClose={() => setVenueId(null)} />
      )}

      <Suspense fallback={null}>
        {view === "recs" && (
          <RecommendationsPanel
            userPos={userPos}
            favCategories={recInterests}
            refreshNonce={refreshNonce}
            city={currentCity?.slug ?? null}
            onSelect={openEvent}
            onOpenCollection={onOpenCollection}
            onPickCategory={onPickCategory}
            onAllCategories={onAllCategories}
            onClose={() => setView("map")}
          />
        )}
        {collection && (
          <CollectionDetail
            open
            slug={collection.slug}
            title={collection.title}
            subtitle={collection.subtitle}
            userPos={userPos}
            interests={recInterests}
            city={currentCity?.slug ?? null}
            onSelect={openEvent}
            onClose={() => setCollection(null)}
          />
        )}
        {view === "favorites" && (
          <FavoritesPanel favIds={fav.ids} userPos={userPos} onSelect={openEvent} onClose={() => setView("map")} />
        )}
        {view === "venues" && <FollowedVenuesPanel onOpenVenue={onOpenVenue} onClose={() => setView("map")} />}
        {view === "friends" && (
          <FriendsPanel
            onFriendsChange={setFriendCount}
            onOpenFriend={setFriendProfile}
            onOpenEvent={openEvent}
            onClose={() => setView("map")}
          />
        )}
        {friendProfile && (
          <FriendProfile
            friend={friendProfile}
            myFavIds={fav.ids}
            userPos={userPos}
            onSelect={openEvent}
            onClose={() => setFriendProfile(null)}
          />
        )}
        {view === "profile" && (
          <ProfilePanel
            user={tgUser}
            city={settingsCity?.name ?? CITY}
            cities={cities}
            onSelectCity={pickCity}
            favIds={fav.ids}
            notifyReminders={notifyReminders}
            onToggleReminders={toggleReminders}
            notifyDigest={notifyDigest}
            onToggleDigest={toggleDigest}
            friendsPrivate={friendsPrivate}
            onToggleFriendsPrivate={toggleFriendsPrivate}
            theme={theme}
            onToggleTheme={toggleTheme}
            onOpenFavorites={() => setView("favorites")}
            onClose={() => setView("map")}
          />
        )}
      </Suspense>

      {friendDisclosure && (
        <FriendDisclosure
          onClose={() => setFriendDisclosure(false)}
          onOpenProfile={() => {
            setFriendDisclosure(false);
            setView("friends");
          }}
        />
      )}

      {friendInvite && (
        <FriendInviteAccept
          invite={friendInvite}
          onClose={() => setFriendInvite(null)}
          onAccepted={() => setView("friends")}
        />
      )}

      <Sidebar
        open={drawerOpen}
        view={view}
        favCount={fav.ids.size}
        venueCount={venueFollows.ids.size}
        friendCount={friendCount}
        user={tgUser}
        onClose={() => setDrawerOpen(false)}
        onSelect={(v) => {
          haptic("light");
          setView(v);
          setDrawerOpen(false);
        }}
      />

      <ProofFrame />

      {!onboarded && <Onboarding onClose={dismissOnboarding} />}

      <Toaster />
      <OfflineBanner />
    </div>
  );
}
