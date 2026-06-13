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
  };
  BackButton?: {
    show: () => void;
    hide: () => void;
    onClick: (cb: () => void) => void;
    offClick: (cb: () => void) => void;
  };
};

export function getWebApp(): TelegramWebApp | undefined {
  return (window as any).Telegram?.WebApp;
}

// Canvas color the page paints behind everything (matches CSS --bg).
const CANVAS = "#0E0F13";

// The app is dark-only; the light theme was removed.
export function initTelegram(): ThemeName {
  const tg = getWebApp();
  document.documentElement.dataset.theme = "dark";
  try {
    tg?.ready();
    tg?.expand();
    tg?.setHeaderColor?.(CANVAS);
    tg?.setBackgroundColor?.(CANVAS);
  } catch {
    /* not running inside Telegram — ignore */
  }
  return "dark";
}

export function haptic(style: "light" | "medium" | "heavy" = "light"): void {
  getWebApp()?.HapticFeedback?.impactOccurred?.(style);
}

export function hapticSelection(): void {
  getWebApp()?.HapticFeedback?.selectionChanged?.();
}
