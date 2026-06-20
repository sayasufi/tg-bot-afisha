import { useSyncExternalStore } from "react";

import { markGoingRemote, syncGoing as syncRemote } from "../api/users";

// «Я иду» / RSVP set, synced per Telegram account (mirrors reminders/favourites). Toggleable:
// markGoing (RSVP, optionally attributing a «Пойдём?» inviter) / unmarkGoing (cancel). localStorage
// is an instant cache + offline fallback; the server is the source of truth once synced.
const KEY = "afisha_going";

function read(): Set<string> {
  try {
    const raw = localStorage.getItem(KEY);
    return new Set(raw ? (JSON.parse(raw) as string[]) : []);
  } catch {
    return new Set();
  }
}

let going = read();
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
  if (sameSet(going, next)) return;
  going = next;
  try {
    localStorage.setItem(KEY, JSON.stringify([...next]));
  } catch {
    /* cache write is best-effort */
  }
  emit();
}

export function markGoing(id: string, inviterId: number | null, sig: string | null = null): void {
  if (going.has(id)) return; // already going — idempotent, the server won't re-notify either
  const next = new Set(going);
  next.add(id);
  setLocal(next); // optimistic — the button flips instantly
  const seq = ++mutationSeq;
  markGoingRemote(id, inviterId, sig, true)
    .then((ids) => {
      if (ids && seq === mutationSeq) setLocal(new Set(ids));
    })
    .catch(() => {
      /* the local mark stands; the next sync reconciles */
    });
}

// Cancel an RSVP — un-«я иду». Optimistic + mutationSeq-guarded like markGoing/favourites.
export function unmarkGoing(id: string): void {
  if (!going.has(id)) return; // not going — nothing to cancel
  const next = new Set(going);
  next.delete(id);
  setLocal(next); // optimistic — the button flips off instantly
  const seq = ++mutationSeq;
  markGoingRemote(id, null, null, false)
    .then((ids) => {
      if (ids && seq === mutationSeq) setLocal(new Set(ids));
    })
    .catch(() => {
      /* the local un-mark stands; the next sync reconciles */
    });
}

let syncing = false;

// Pull the account's going set. Called once on app start. No-op outside Telegram.
export async function syncGoing(): Promise<void> {
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

function subscribe(cb: () => void): () => void {
  subscribers.add(cb);
  return () => {
    subscribers.delete(cb);
  };
}

function getSnapshot(): Set<string> {
  return going;
}

export function useGoing() {
  const ids = useSyncExternalStore(subscribe, getSnapshot);
  return {
    ids,
    has: (id: string) => ids.has(id),
    mark: markGoing,
    unmark: unmarkGoing,
  };
}
