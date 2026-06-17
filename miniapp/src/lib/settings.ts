import { syncSettings } from "../api/users";

// Account-scoped settings (synced per Telegram account, not per device). Theme and the
// picked city go through here; any future setting is just another key — push it with
// pushSetting(key, value) and read it from loadSettings() on open.
export type Prefs = { theme?: string; city?: string } & Record<string, unknown>;

// Pull the account's settings on app open (null outside Telegram / on error).
export async function loadSettings(): Promise<Prefs | null> {
  return (await syncSettings()) as Prefs | null;
}

// Persist one setting to the account (fire-and-forget; local state already updated).
export function pushSetting(key: string, value: unknown): void {
  void syncSettings({ [key]: value });
}
