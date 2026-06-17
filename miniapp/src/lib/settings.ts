import { syncSettings, type UserSettings } from "../api/users";

// Account-scoped settings (synced per Telegram account, not per device). Theme, picked
// city and the first-run flags go through here. localStorage stays as the instant cache.
export type Settings = UserSettings;

// Pull the account's settings on app open (null outside Telegram / on error).
export async function loadSettings(): Promise<Settings | null> {
  return syncSettings();
}

// Persist one setting to the account (fire-and-forget; local state already updated).
export function pushSetting<K extends keyof Settings>(key: K, value: Settings[K]): void {
  void syncSettings({ [key]: value } as Partial<Settings>);
}
