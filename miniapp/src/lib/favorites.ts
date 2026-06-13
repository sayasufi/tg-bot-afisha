import { useEffect, useState } from "react";

// Favorites are stored locally (per device) as a set of event ids.
const KEY = "afisha_favorites";

function read(): Set<string> {
  try {
    const raw = localStorage.getItem(KEY);
    return new Set(raw ? (JSON.parse(raw) as string[]) : []);
  } catch {
    return new Set();
  }
}

let favs = read();
const subscribers = new Set<() => void>();

function emit() {
  for (const fn of subscribers) fn();
}

export function toggleFavorite(id: string): void {
  favs = new Set(favs);
  if (favs.has(id)) favs.delete(id);
  else favs.add(id);
  try {
    localStorage.setItem(KEY, JSON.stringify([...favs]));
  } catch {
    /* storage unavailable — keep in-memory */
  }
  emit();
}

// Reactive hook: re-renders subscribers whenever favorites change.
export function useFavorites() {
  const [, force] = useState(0);
  useEffect(() => {
    const fn = () => force((x) => x + 1);
    subscribers.add(fn);
    return () => {
      subscribers.delete(fn);
    };
  }, []);
  return {
    ids: favs,
    has: (id: string) => favs.has(id),
    toggle: toggleFavorite,
  };
}
