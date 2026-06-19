// A lightweight behavioural profile kept on-device: the categories of events you
// open. Sent with recommendation requests so the feed learns your taste beyond
// the categories you explicitly favourite (implicit feedback → personalisation).
const KEY = "okrest_recent_cat";
const CAP = 60;

export function recordOpen(category: string | null | undefined): void {
  if (!category) return;
  try {
    const arr: string[] = JSON.parse(localStorage.getItem(KEY) || "[]");
    arr.push(category);
    localStorage.setItem(KEY, JSON.stringify(arr.slice(-CAP)));
  } catch {
    /* ignore */
  }
}

export function recentCategories(): string[] {
  try {
    const arr = JSON.parse(localStorage.getItem(KEY) || "[]");
    return Array.isArray(arr) ? arr.filter((x) => typeof x === "string") : [];
  } catch {
    return [];
  }
}

// «Просмотрено» — unique events you've opened, kept on-device. A real engagement metric for the
// profile (you can't read it off the Избранное list). Per-device by design; it's a soft count.
const VIEWED_KEY = "okrest_viewed";
const VIEWED_CAP = 4000;

export function recordViewed(id: string | null | undefined): void {
  if (!id) return;
  try {
    const arr: string[] = JSON.parse(localStorage.getItem(VIEWED_KEY) || "[]");
    if (arr.includes(id)) return; // unique events only
    arr.push(id);
    localStorage.setItem(VIEWED_KEY, JSON.stringify(arr.slice(-VIEWED_CAP)));
  } catch {
    /* ignore */
  }
}

export function viewedCount(): number {
  try {
    const arr = JSON.parse(localStorage.getItem(VIEWED_KEY) || "[]");
    return Array.isArray(arr) ? new Set(arr).size : 0;
  } catch {
    return 0;
  }
}
