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
  const next = new Set(favs);
  if (next.has(id)) next.delete(id);
  else next.add(id);
  // Persist first so a (very unlikely) storage failure doesn't leave the
  // in-memory state diverged from what reloads — only commit on success.
  try {
    localStorage.setItem(KEY, JSON.stringify([...next]));
  } catch {
    return; // keep the previous state; the toggle is a no-op
  }
  favs = next;
  emit();
}

// Reactive hook: re-renders subscribers whenever favorites change. `ids` is a
// fresh copy so callers can't mutate the store directly (only toggle() can).
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
    ids: new Set(favs),
    has: (id: string) => favs.has(id),
    toggle: toggleFavorite,
  };
}
