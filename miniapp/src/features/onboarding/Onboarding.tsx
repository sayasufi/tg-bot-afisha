import { useState, type CSSProperties } from "react";

import { CATEGORIES } from "../../lib/categories";
import { IconHeart, IconSearch } from "../../lib/icons";
import { CategoryIcon } from "../../lib/icons/category";

// One-time first-run flow. STEP 1 asks what the visitor likes (so «Для тебя» is warm from
// the very first open instead of a popularity list mislabelled as personal — the cold-start
// fix). STEP 2 is a VITRINE "exhibition handout": where the hidden bits live (search, filter,
// the sections behind ☰). `onClose` carries the picked category slugs back to persist them.
const STEPS = [
  {
    glyph: <span className="onboard__char">▦</span>,
    title: "Карта вокруг",
    text: "Каждая табличка — событие поблизости. Нажми, чтобы открыть карточку.",
  },
  {
    glyph: <IconSearch size={18} />,
    title: "Поиск",
    text: "Лупа справа сверху — ищи по названию, месту или коду события.",
  },
  {
    glyph: <span className="onboard__char">≡</span>,
    title: "Когда и «сейчас»",
    text: "Плашка сверху — фильтр по дате и теме, и «можно пойти прямо сейчас».",
  },
  {
    glyph: <IconHeart size={18} />,
    title: "Подборка и избранное",
    text: "Меню ☰ слева: персональная подборка, профиль и сохранённое сердечком.",
  },
];

const MIN_PICK = 3;
// "other" is a catch-all bucket, not a taste — leave it out of the picker.
const PICKABLE = CATEGORIES.filter((c) => c.key !== "other");

export function Onboarding({ onClose }: { onClose: (interests: string[]) => void }) {
  const [step, setStep] = useState<0 | 1>(0);
  const [picked, setPicked] = useState<string[]>([]);
  const toggle = (key: string) =>
    setPicked((p) => (p.includes(key) ? p.filter((k) => k !== key) : [...p, key]));

  if (step === 0) {
    const left = MIN_PICK - picked.length;
    return (
      <div className="onboard" role="dialog" aria-modal="true" aria-label="Что вам интересно">
        <div className="onboard__sheet">
          <span className="kicker kicker--code">Окрест · вкусы</span>
          <h2 className="onboard__title">что вам интересно?</h2>
          <p className="onboard__lede">
            Выберите темы — соберу «Для тебя» из них. Поменять можно в любой момент.
          </p>
          <div className="onboard__cats" role="group" aria-label="Темы">
            {PICKABLE.map((c) => {
              const on = picked.includes(c.key);
              return (
                <button
                  key={c.key}
                  type="button"
                  className={`onboard__cat${on ? " onboard__cat--active" : ""}`}
                  style={{ "--cat": c.color } as CSSProperties}
                  aria-pressed={on}
                  onClick={() => toggle(c.key)}
                >
                  <span className="onboard__caticon" aria-hidden="true">
                    <CategoryIcon cat={c.key} size={20} />
                  </span>
                  <span className="onboard__catlabel">{c.label}</span>
                </button>
              );
            })}
          </div>
          <button
            type="button"
            className="onboard__cta"
            disabled={picked.length < MIN_PICK}
            onClick={() => setStep(1)}
          >
            {left > 0 ? `Выберите ещё ${left}` : "Далее"}
          </button>
          <button type="button" className="onboard__skip" onClick={() => onClose(picked)}>
            Пропустить
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="onboard" role="dialog" aria-modal="true" aria-label="Знакомство с приложением">
      <div className="onboard__sheet">
        <span className="kicker kicker--code">Окрест · путеводитель</span>
        <h2 className="onboard__title">что вокруг прямо сейчас</h2>
        <ul className="onboard__list">
          {STEPS.map((s) => (
            <li className="onboard__row" key={s.title}>
              <span className="onboard__glyph" aria-hidden="true">
                {s.glyph}
              </span>
              <span className="onboard__body">
                <b className="onboard__rowtitle">{s.title}</b>
                <span className="onboard__rowtext">{s.text}</span>
              </span>
            </li>
          ))}
        </ul>
        <button type="button" className="onboard__cta" onClick={() => onClose(picked)}>
          Понятно
        </button>
      </div>
    </div>
  );
}
