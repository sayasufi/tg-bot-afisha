import { useEffect, useMemo, useState } from "react";

import { fetchCities, type City } from "../api/client";
import { distanceMeters } from "./distance";

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

  useEffect(() => {
    const ctrl = new AbortController();
    fetchCities(ctrl.signal)
      .then(setCities)
      .catch(() => {});
    return () => ctrl.abort();
  }, []);

  const current = useMemo<City | null>(() => {
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

  const select = (slug: string) => {
    setChosen(slug);
    try {
      localStorage.setItem(LS_KEY, slug);
    } catch {
      /* ignore */
    }
  };

  return { cities, current, select };
}
