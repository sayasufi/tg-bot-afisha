// Канонический признак ПК-раскладки (ширина, НЕ auth — за auth отвечает isWebMode).
// Единственный источник брейкпойнта: тот же 1024px, что и в styles/desktop.css.
// Telegram Desktop (окно ~420-480px) сюда не попадает — и это норма: он живёт мобильной вёрсткой.
import { useSyncExternalStore } from "react";

const QUERY = "(min-width: 1024px)";

function subscribe(cb: () => void): () => void {
  const mq = window.matchMedia(QUERY);
  mq.addEventListener("change", cb);
  return () => mq.removeEventListener("change", cb);
}

function snapshot(): boolean {
  return window.matchMedia(QUERY).matches;
}

export function useIsDesktop(): boolean {
  return useSyncExternalStore(subscribe, snapshot);
}

// Для не-React кода (редко; в компонентах использовать хук — он реагирует на ресайз).
export function isDesktopNow(): boolean {
  try {
    return window.matchMedia(QUERY).matches;
  } catch {
    return false;
  }
}
