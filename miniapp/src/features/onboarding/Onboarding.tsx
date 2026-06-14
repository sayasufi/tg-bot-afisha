import { useState } from "react";

import { haptic } from "../../lib/telegram";

// Two-screen first-run intro. Shown once (guarded by a localStorage flag in
// App). VITRINE voice: a gallery you carry in your pocket.
const SCREENS = [
  {
    kicker: "Окрест · Москва",
    title: "город как\nвыставка",
    text: "Карта культурных событий вокруг тебя: концерты, выставки, спектакли, лекции — всё на одном плане.",
    glyph: (
      <svg viewBox="0 0 64 64" width="72" height="72" aria-hidden="true">
        <rect x="6" y="6" width="52" height="52" fill="none" stroke="currentColor" strokeWidth="2" />
        <circle cx="32" cy="29" r="9" fill="none" stroke="currentColor" strokeWidth="2" />
        <circle cx="32" cy="29" r="2.5" fill="currentColor" />
        <line x1="32" y1="38" x2="32" y2="50" stroke="currentColor" strokeWidth="2" />
      </svg>
    ),
  },
  {
    kicker: "Как смотреть",
    title: "тапни,\nсохрани, иди",
    text: "Тапни по точке — откроется карточка с местом и маршрутом. Сердечко добавит событие в избранное. Фильтры подберут вечер по дате, цене и вкусу.",
    glyph: (
      <svg viewBox="0 0 64 64" width="72" height="72" aria-hidden="true">
        <path d="M32 52s-16-10-16-22a9 9 0 0 1 16-5.6A9 9 0 0 1 48 30c0 12-16 22-16 22Z" fill="none" stroke="currentColor" strokeWidth="2" strokeLinejoin="round" />
      </svg>
    ),
  },
];

export function Onboarding({ onDone }: { onDone: () => void }) {
  const [i, setI] = useState(0);
  const last = i === SCREENS.length - 1;
  const s = SCREENS[i];

  const next = () => {
    haptic("light");
    if (last) onDone();
    else setI((n) => n + 1);
  };

  return (
    <div className="onb" role="dialog" aria-modal="true">
      <button type="button" className="onb__skip" onClick={onDone}>
        Пропустить
      </button>
      <div className="onb__stage" key={i}>
        <div className="onb__glyph">{s.glyph}</div>
        <span className="kicker onb__kicker">{s.kicker}</span>
        <h2 className="onb__title">
          {s.title.split("\n").map((line, k) => (
            <span key={k}>{line}</span>
          ))}
        </h2>
        <p className="onb__text">{s.text}</p>
      </div>
      <div className="onb__foot">
        <div className="onb__dots">
          {SCREENS.map((_, k) => (
            <span key={k} className={`onb__dot${k === i ? " onb__dot--on" : ""}`} />
          ))}
        </div>
        <button type="button" className="onb__next" onClick={next}>
          {last ? "Открыть карту" : "Дальше"}
        </button>
      </div>
    </div>
  );
}
