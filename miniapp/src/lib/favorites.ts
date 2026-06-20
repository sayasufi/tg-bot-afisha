import { useSyncExternalStore } from "react";

import { syncFavorites as syncRemote, toggleFavoriteRemote } from "../api/users";

// Favorites sync per Telegram account (server-side). localStorage is kept as an instant
// cache + offline/non-Telegram fallback; the server is the source of truth once synced.
const KEY = "afisha_favorites";
// Set once per device after we've merged this device's local favourites into the
// account — so we migrate old per-device hearts up exactly once, then become pull-only.
const MERGED_KEY = "afisha_favorites_merged";

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
// Monotonic counter of LOCAL mutations — a server response only adopts if no newer local
// toggle happened since its request was issued (otherwise a stale list clobbers a fresh tap).
let mutationSeq = 0;

function emit() {
  for (const fn of subscribers) fn();
}

function sameSet(a: Set<string>, b: Set<string>): boolean {
  if (a.size !== b.size) return false;
  for (const x of a) if (!b.has(x)) return false;
  return true;
}

function setLocal(next: Set<string>): void {
  if (sameSet(favs, next)) return; // no-op (e.g. server adopt returns the same list) → no re-render
  favs = next; // new identity ONLY on a real change → referential stability for consumers
  try {
    localStorage.setItem(KEY, JSON.stringify([...next]));
  } catch {
    /* cache write is best-effort */
  }
  emit();
}

export function toggleFavorite(id: string): void {
  const next = new Set(favs);
  const on = !next.has(id);
  if (on) next.add(id);
  else next.delete(id);
  setLocal(next); // optimistic — the UI flips instantly
  const seq = ++mutationSeq;
  // Persist to the account; adopt the server list back ONLY if this is still the latest
  // local op (a later toggle must not be overwritten by this one's stale response).
  toggleFavoriteRemote(id, on)
    .then((ids) => {
      if (ids && seq === mutationSeq) setLocal(new Set(ids));
    })
    .catch(() => {
      /* the local toggle already stands; next sync reconciles */
    });
}

// «Пойдём?» invite accepted → favourite the event AND attribute the inviter so the bot DMs them once
// (server-deduped). Ensures favourited; harmless if already so (the server's "newly added" check
// stops a duplicate DM).
export function acceptInvite(id: string, inviter: number, sig: string): void {
  if (!favs.has(id)) {
    const next = new Set(favs);
    next.add(id);
    setLocal(next); // optimistic
  }
  const seq = ++mutationSeq;
  toggleFavoriteRemote(id, true, inviter, sig)
    .then((ids) => {
      if (ids && seq === mutationSeq) setLocal(new Set(ids));
    })
    .catch(() => {
      /* the local add stands; next sync reconciles */
    });
}

let syncing = false;

// Pull the account's favourites (merging this device's local ones on its first run).
// Called once on app start. No-op / keeps local set when outside Telegram or offline.
export async function syncFavorites(): Promise<void> {
  if (syncing) return;
  syncing = true;
  try {
    let merged = false;
    try {
      merged = localStorage.getItem(MERGED_KEY) === "1";
    } catch {
      /* ignore */
    }
    const seq = mutationSeq;
    const ids = await syncRemote(merged ? [] : [...favs]);
    if (ids) {
      if (seq === mutationSeq) setLocal(new Set(ids)); // don't clobber a toggle made mid-sync
      try {
        localStorage.setItem(MERGED_KEY, "1");
      } catch {
        /* ignore */
      }
    }
  } finally {
    syncing = false;
  }
}

function subscribe(cb: () => void): () => void {
  subscribers.add(cb);
  return () => {
    subscribers.delete(cb);
  };
}

// `favs` is replaced (new identity) only on a real change, so the snapshot is stable
// between unrelated renders — consumers' memos keyed on fav.ids no longer thrash.
function getSnapshot(): Set<string> {
  return favs;
}

export function useFavorites() {
  const ids = useSyncExternalStore(subscribe, getSnapshot);
  return {
    ids,
    has: (id: string) => ids.has(id),
    toggle: toggleFavorite,
    accept: acceptInvite,
  };
}
