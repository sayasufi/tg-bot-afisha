export type ThemeName = "dark" | "light";

type TelegramWebApp = {
  ready: () => void;
  expand: () => void;
  colorScheme?: ThemeName;
  themeParams?: Record<string, string>;
  setHeaderColor?: (color: string) => void;
  setBackgroundColor?: (color: string) => void;
  HapticFeedback?: {
    impactOccurred?: (style: "light" | "medium" | "heavy" | "rigid" | "soft") => void;
    selectionChanged?: () => void;
    notificationOccurred?: (type: "error" | "success" | "warning") => void;
  };
  BackButton?: {
    show: () => void;
    hide: () => void;
    onClick: (cb: () => void) => void;
    offClick: (cb: () => void) => void;
  };
  openTelegramLink?: (url: string) => void;
  openLink?: (url: string, options?: { try_instant_view?: boolean }) => void;
  initData?: string;
  isVersionAtLeast?: (version: string) => boolean;
  shareMessage?: (msgId: string, callback?: (sent: boolean) => void) => void;
  disableVerticalSwipes?: () => void; // Bot API 7.7+ — stop pull-to-close hijacking in-app scrolls
};

const BOT_LINK = "https://t.me/okrestmap_bot";

// Share an event via Telegram's native share sheet (falls back to the Web
// Share API, then a plain share link).
export function shareEvent(opts: { title: string; text?: string; url?: string | null }): void {
  const url = opts.url || BOT_LINK;
  const text = [opts.title, opts.text].filter(Boolean).join("\n");
  const share = `https://t.me/share/url?url=${encodeURIComponent(url)}&text=${encodeURIComponent(text)}`;
  const wa = getWebApp();
  if (wa?.openTelegramLink) {
    wa.openTelegramLink(share);
    return;
  }
  if (typeof navigator !== "undefined" && (navigator as any).share) {
    (navigator as any).share({ title: opts.title, text, url }).catch(() => undefined);
    return;
  }
  window.open(share, "_blank");
}

export function getWebApp(): TelegramWebApp | undefined {
  return (window as any).Telegram?.WebApp;
}

export type TgUser = { id: number; first_name?: string; last_name?: string; username?: string; photo_url?: string };

export function getUser(): TgUser | null {
  return (getWebApp() as any)?.initDataUnsafe?.user ?? null;
}

// Canvas colour the page paints behind everything (matches CSS --bg per theme).
const CANVAS: Record<ThemeName, string> = { light: "#F4F4EF", dark: "#14130E" };
const THEME_KEY = "okrest_theme";

export function getSavedTheme(): ThemeName {
  try {
    return localStorage.getItem(THEME_KEY) === "dark" ? "dark" : "light";
  } catch {
    return "light";
  }
}

// Apply a theme: set the document flag, match the Telegram chrome, and persist.
export function applyTheme(theme: ThemeName): void {
  document.documentElement.dataset.theme = theme;
  // Match the browser/OS chrome (status bar, address bar) to the theme. Inside
  // Telegram setHeaderColor handles this; the <meta> covers plain-browser users,
  // who otherwise got a hardcoded-light bar even in dark mode.
  const meta = document.querySelector('meta[name="theme-color"]');
  if (meta) meta.setAttribute("content", CANVAS[theme]);
  const tg = getWebApp();
  try {
    tg?.setHeaderColor?.(CANVAS[theme]);
    tg?.setBackgroundColor?.(CANVAS[theme]);
  } catch {
    /* not running inside Telegram — ignore */
  }
  try {
    localStorage.setItem(THEME_KEY, theme);
  } catch {
    /* ignore */
  }
}

// VITRINE bootstrap — applies the saved theme (defaults to the white-cube).
export function initTelegram(): ThemeName {
  const tg = getWebApp();
  const theme = getSavedTheme();
  try {
    tg?.ready();
    tg?.expand();
    // Stop Telegram's pull-to-close gesture from hijacking vertical scrolls/swipes inside the App
    // (the event sheet swipe, the recommendations rail) and yanking the Mini App shut. Version-gated:
    // the method only exists on Bot API 7.7+ (older clients silently lack it).
    tg?.disableVerticalSwipes?.();
  } catch {
    /* not running inside Telegram — ignore */
  }
  applyTheme(theme);
  return theme;
}

export function haptic(style: "light" | "medium" | "heavy" = "light"): void {
  getWebApp()?.HapticFeedback?.impactOccurred?.(style);
}

export function hapticSelection(): void {
  getWebApp()?.HapticFeedback?.selectionChanged?.();
}

export function hapticNotify(type: "success" | "warning" | "error" = "success"): void {
  getWebApp()?.HapticFeedback?.notificationOccurred?.(type);
}
