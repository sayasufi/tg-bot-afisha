type ThemeName = "dark" | "light";

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

// Canvas color the page paints behind everything (matches CSS --bg).
const CANVAS = "#F4F4EF";

// VITRINE — white-cube gallery, light-only theme.
export function initTelegram(): ThemeName {
  const tg = getWebApp();
  document.documentElement.dataset.theme = "light";
  try {
    tg?.ready();
    tg?.expand();
    tg?.setHeaderColor?.(CANVAS);
    tg?.setBackgroundColor?.(CANVAS);
  } catch {
    /* not running inside Telegram — ignore */
  }
  return "light";
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
