import { useEffect, useMemo, useState } from "react";

import { fetchCities, type City } from "../api/client";
import { distanceMeters } from "./distance";
import { pushSetting } from "./settings";

const LS_KEY = "okrest:city";

function readStored(): string | null {
  try {
    return localStorage.getItem(LS_KEY);
  } catch {
    return null; // some webviews restrict storage
  }
}

// Active cities + the current one. Selection priority: an explicit prior choice
// (persisted) → the nearest active city by geolocation → the first active city. Only an
// explicit pick via `select` is persisted, so auto-detect keeps following the user until
// they choose. Returns the full list so a switcher can render when there's more than one.
export function useCities(userPos: [number, number] | null) {
  const [cities, setCities] = useState<City[]>([]);
  const [chosen, setChosen] = useState<string | null>(readStored);
  // Transient map-only override (a city tapped on the picker / zoomed onto manually). NOT persisted — the
  // map just SHOWS that city's events; the SAVED city (settings/profile) stays put.
  const [viewing, setViewing] = useState<string | null>(null);

  useEffect(() => {
    const ctrl = new AbortController();
    fetchCities(ctrl.signal)
      .then(setCities)
      .catch(() => {});
    return () => ctrl.abort();
  }, []);

  // The SAVED city (settings/profile): explicit prior choice (persisted) → nearest active by geo → first.
  const settingsCity = useMemo<City | null>(() => {
    if (!cities.length) return null;
    const pick = chosen && cities.find((c) => c.slug === chosen);
    if (pick) return pick;
    if (userPos) {
      let best = cities[0];
      let bestD = Infinity;
      for (const c of cities) {
        const d = distanceMeters(userPos, [c.lat, c.lon]);
        if (d < bestD) {
          bestD = d;
          best = c;
        }
      }
      return best;
    }
    return cities[0];
  }, [cities, chosen, userPos]);

  // The EFFECTIVE current city the map/events/recs/search use: the transient map view if one is set,
  // otherwise the saved city. So tapping/zooming a city on the map shows its events WITHOUT touching settings.
  const current = useMemo<City | null>(() => {
    if (viewing) {
      const v = cities.find((c) => c.slug === viewing);
      if (v) return v;
    }
    return settingsCity;
  }, [viewing, cities, settingsCity]);

  const setChosenLocal = (slug: string) => {
    setChosen(slug);
    try {
      localStorage.setItem(LS_KEY, slug);
    } catch {
      /* ignore */
    }
  };

  // Explicit user pick from the PROFILE → persist (local + account) and drop any transient map view, so the
  // saved city is the source of truth again. The ONLY writer of the saved city.
  const select = (slug: string) => {
    setChosenLocal(slug);
    pushSetting("city", slug);
    setViewing(null);
  };

  // Map-only view of a city (tap on the picker / manual zoom onto a city) — transient, NOT persisted.
  const view = (slug: string) => setViewing(slug);

  // Seed from the account on load (no server write-back — we just read it).
  const seed = (slug: string) => {
    if (slug && slug !== chosen) setChosenLocal(slug);
  };

  return { cities, current, settingsCity, select, view, seed };
}
