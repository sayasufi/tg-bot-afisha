import { useSyncExternalStore } from "react";

import { syncVenueFollows as syncRemote, toggleVenueFollowRemote } from "../api/users";

// Followed venues synced per Telegram account (server-side), mirroring reminders/favourites.
// localStorage is an instant cache + offline/non-Telegram fallback; the server is the source
// of truth once synced. A follow = "this place is on my radar" (and a future bot trigger).
const KEY = "afisha_venue_follows";

function read(): Set<string> {
  try {
    const raw = localStorage.getItem(KEY);
    return new Set(raw ? (JSON.parse(raw) as string[]) : []);
  } catch {
    return new Set();
  }
}

let follows = read();
const subscribers = new Set<() => void>();
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
  if (sameSet(follows, next)) return;
  follows = next;
  try {
    localStorage.setItem(KEY, JSON.stringify([...next]));
  } catch {
    /* cache write is best-effort */
  }
  emit();
}

export function toggleVenueFollow(id: string): void {
  const next = new Set(follows);
  const on = !next.has(id);
  if (on) next.add(id);
  else next.delete(id);
  setLocal(next); // optimistic — the button flips instantly
  const seq = ++mutationSeq;
  toggleVenueFollowRemote(id, on)
    .then((ids) => {
      if (ids && seq === mutationSeq) setLocal(new Set(ids));
    })
    .catch(() => {
      /* the local toggle stands; next sync reconciles */
    });
}

let syncing = false;

// Pull the account's followed venues. Called once on app start. No-op outside Telegram.
export async function syncVenueFollows(): Promise<void> {
  if (syncing) return;
  syncing = true;
  try {
    const seq = mutationSeq;
    const ids = await syncRemote();
    if (ids && seq === mutationSeq) setLocal(new Set(ids));
  } finally {
    syncing = false;
  }
}

// Seed from a pre-fetched list (the on-open /bootstrap pulls follows alongside the rest in one round-trip).
// Capture the seq up front, adopt only if no local toggle raced it — mirrors syncVenueFollows' guard.
export function beginVenueFollowsAdopt(): (ids: string[]) => void {
  const seq = mutationSeq;
  return (ids: string[]) => {
    if (seq === mutationSeq) setLocal(new Set(ids));
  };
}

function subscribe(cb: () => void): () => void {
  subscribers.add(cb);
  return () => {
    subscribers.delete(cb);
  };
}

function getSnapshot(): Set<string> {
  return follows;
}

export function useVenueFollows() {
  const ids = useSyncExternalStore(subscribe, getSnapshot);
  return {
    ids,
    has: (id: string) => ids.has(id),
    toggle: toggleVenueFollow,
  };
}
