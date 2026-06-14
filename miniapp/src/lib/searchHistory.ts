// Recent search queries, stored locally (per device). Most-recent first, capped.
const KEY = "okrest_search_history";
const CAP = 6;

export function readHistory(): string[] {
  try {
    const raw = localStorage.getItem(KEY);
    const arr = raw ? (JSON.parse(raw) as unknown) : [];
    return Array.isArray(arr) ? arr.filter((x): x is string => typeof x === "string").slice(0, CAP) : [];
  } catch {
    return [];
  }
}

export function pushHistory(query: string): void {
  const q = query.trim();
  if (q.length < 2) return;
  const prev = readHistory().filter((x) => x.toLowerCase() !== q.toLowerCase());
  const next = [q, ...prev].slice(0, CAP);
  try {
    localStorage.setItem(KEY, JSON.stringify(next));
  } catch {
    /* ignore quota/serialisation failures — history is best-effort */
  }
}

export function clearHistory(): void {
  try {
    localStorage.removeItem(KEY);
  } catch {
    /* ignore */
  }
}
