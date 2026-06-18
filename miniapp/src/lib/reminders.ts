import { useSyncExternalStore } from "react";

import { syncReminders as syncRemote, toggleReminderRemote } from "../api/users";

// Event reminders synced per Telegram account (server-side), mirroring favourites.
// localStorage is an instant cache + offline/non-Telegram fallback; the server is the
// source of truth once synced. A reminder = "the bot DMs me ~2h before this event".
const KEY = "afisha_reminders";

function read(): Set<string> {
  try {
    const raw = localStorage.getItem(KEY);
    return new Set(raw ? (JSON.parse(raw) as string[]) : []);
  } catch {
    return new Set();
  }
}

let rems = read();
const subscribers = new Set<() => void>();
// Monotonic local-mutation counter — a server response only adopts if no newer local
// toggle happened since its request was issued (stale list must not clobber a fresh tap).
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
  if (sameSet(rems, next)) return; // no-op (e.g. server adopt returns the same list) → no re-render
  rems = next; // new identity ONLY on a real change → referential stability for consumers
  try {
    localStorage.setItem(KEY, JSON.stringify([...next]));
  } catch {
    /* cache write is best-effort */
  }
  emit();
}

export function toggleReminder(id: string): void {
  const next = new Set(rems);
  const on = !next.has(id);
  if (on) next.add(id);
  else next.delete(id);
  setLocal(next); // optimistic — the bell flips instantly
  const seq = ++mutationSeq;
  // The server may REJECT an "on" (event has no upcoming session → can't remind): adopt
  // the returned list so the bell reflects reality, but only if this is still the latest op.
  toggleReminderRemote(id, on)
    .then((ids) => {
      if (ids && seq === mutationSeq) setLocal(new Set(ids));
    })
    .catch(() => {
      /* the local toggle stands; next sync reconciles */
    });
}

let syncing = false;

// Pull the account's active reminders. Called once on app start. No-op outside Telegram.
export async function syncReminders(): Promise<void> {
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
  return rems;
}

export function useReminders() {
  const ids = useSyncExternalStore(subscribe, getSnapshot);
  return {
    ids,
    has: (id: string) => ids.has(id),
    toggle: toggleReminder,
  };
}
