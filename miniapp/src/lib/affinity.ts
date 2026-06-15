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
