import { useState } from "react";

import { CATEGORIES } from "../../lib/categories";
import { CategoryIcon } from "../../lib/icons/category";
import { haptic } from "../../lib/telegram";

// One-time first-run screen: ask what the visitor likes so «Для тебя» is warm from the very
// first open. Single screen on purpose — the old 4-step text guide was a wall nobody reads;
// the map teaches itself and the in-context Coach handles "show me what's around". `onClose`
// carries the picked category slugs back to persist them.
const MIN_PICK = 3;
// "other" is a catch-all bucket, not a taste — leave it out of the picker.
const PICKABLE = CATEGORIES.filter((c) => c.key !== "other");

export function Onboarding({ onClose }: { onClose: (interests: string[]) => void }) {
  const [picked, setPicked] = useState<string[]>([]);
  const toggle = (key: string) => {
    haptic("light");
    setPicked((p) => (p.includes(key) ? p.filter((k) => k !== key) : [...p, key]));
  };
  const ready = picked.length >= MIN_PICK;
  const left = MIN_PICK - picked.length;
  const finish = () => {
    haptic(ready ? "medium" : "light");
    onClose(picked);
  };

  return (
    <div className="onboard" role="dialog" aria-modal="true" aria-label="Что вам интересно">
      <div className="onboard__sheet">
        <span className="onboard__kicker">ОКРЕСТ · НАСТРОЙКА</span>
        <h2 className="onboard__title">что вам интересно?</h2>
        <p className="onboard__lede">
          Отметьте темы — и «Для тебя» соберётся под вас. Поменять можно когда угодно.
        </p>

        <div className="onboard__cats" role="group" aria-label="Темы">
          {PICKABLE.map((c, i) => {
            const on = picked.includes(c.key);
            return (
              <button
                key={c.key}
                type="button"
                className={`onboard__cat${on ? " onboard__cat--active" : ""}`}
                style={{ animationDelay: `${0.04 * i + 0.04}s`, ["--cat" as string]: c.color }}
                aria-pressed={on}
                onClick={() => toggle(c.key)}
              >
                <span className="onboard__caticon" aria-hidden="true">
                  <CategoryIcon cat={c.key} size={25} />
                </span>
                <span className="onboard__catlabel">{c.label}</span>
              </button>
            );
          })}
        </div>

        <div className="onboard__foot">
          <button
            type="button"
            className={`onboard__cta${ready ? " onboard__cta--ready" : ""}`}
            disabled={!ready}
            onClick={finish}
          >
            {ready ? `Собрать ленту · ${picked.length} →` : `Выберите ещё ${left}`}
          </button>
          <button type="button" className="onboard__skip" onClick={() => onClose(picked)}>
            пропустить
          </button>
        </div>
      </div>
    </div>
  );
}
