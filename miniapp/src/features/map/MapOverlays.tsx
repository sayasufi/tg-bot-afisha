import { useEffect, useState } from "react";

// Lightweight map-screen states: a top loading bar, an empty-result card, and a
// one-time coach hint pointing at the locate button.

// Time-of-day tint over the map — a soft wash that warms toward evening and
// cools/dims at night (no full dark theme, just a living sense of the hour).
function toneForHour(h: number): { rgb: string; o: number } {
  if (h < 6) return { rgb: "26, 35, 72", o: 0.16 }; // night — deep blue dusk
  if (h < 11) return { rgb: "180, 214, 255", o: 0.07 }; // morning — cool light
  if (h < 17) return { rgb: "255, 255, 255", o: 0 }; // midday — clear
  if (h < 21) return { rgb: "255, 168, 64", o: 0.12 }; // evening — golden
  return { rgb: "58, 42, 90", o: 0.14 }; // late — violet dusk
}

export function MapTone() {
  const [tone, setTone] = useState(() => toneForHour(new Date().getHours()));
  useEffect(() => {
    const id = setInterval(() => setTone(toneForHour(new Date().getHours())), 5 * 60 * 1000);
    return () => clearInterval(id);
  }, []);
  return <div className="map-tone" style={{ background: `rgba(${tone.rgb}, ${tone.o})` }} aria-hidden="true" />;
}

// Radar sweep from the user on each locate tap — echoes the logo / "вокруг тебя".
// Keyed by the locate nonce in App so it remounts and replays each tap.
export function RadarPing({ nonce }: { nonce: number }) {
  if (!nonce) return null;
  return (
    <div className="radar" aria-hidden="true">
      <span />
      <span />
      <span />
    </div>
  );
}

export function LoadingBar({ show }: { show: boolean }) {
  if (!show) return null;
  return (
    <div className="loadbar" aria-hidden="true">
      <span />
    </div>
  );
}

export function EmptyState({ onReset }: { onReset: () => void }) {
  return (
    <div className="emptystate" role="status">
      <div className="emptystate__card">
        <svg className="emptystate__mark" viewBox="0 0 48 48" aria-hidden="true">
          <circle cx="21" cy="21" r="13" fill="none" stroke="currentColor" strokeWidth="3" />
          <line x1="31" y1="31" x2="42" y2="42" stroke="currentColor" strokeWidth="3" strokeLinecap="round" />
        </svg>
        <div className="emptystate__title">Вокруг пусто</div>
        <p className="emptystate__text">Под выбранные фильтры ничего не нашлось. Попробуй расширить даты или категории.</p>
        <button type="button" className="btn btn--primary emptystate__btn" onClick={onReset}>
          Сбросить фильтры
        </button>
      </div>
    </div>
  );
}

export function Coach({ onDismiss }: { onDismiss: () => void }) {
  return (
    <button type="button" className="coach" onClick={onDismiss} aria-label="Понятно">
      Нажми — покажу, что вокруг
    </button>
  );
}
