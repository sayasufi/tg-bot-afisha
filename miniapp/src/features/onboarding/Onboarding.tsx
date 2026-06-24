import { useEffect, useState } from "react";

import { API_BASE } from "../../api/http";
import { CATEGORIES } from "../../lib/categories";
import { CategoryIcon } from "../../lib/icons/category";
import { haptic } from "../../lib/telegram";

// One-time first-run screen: ask what the visitor likes so «Для тебя» is warm from the very first
// open. Single screen on purpose — the old 4-step text guide was a wall nobody reads. Each theme is a
// PHOTO tile (a real, recent Moscow poster behind it) — it reads as the start of a culture guide, not a
// settings form, which is the whole point. `onClose` carries the picked category slugs back to persist.
const MIN_PICK = 3;
// "other" is a catch-all bucket, not a taste — leave it out of the picker.
const PICKABLE = CATEGORIES.filter((c) => c.key !== "other");

export function Onboarding({ onClose }: { onClose: (interests: string[]) => void }) {
  const [picked, setPicked] = useState<string[]>([]);
  const [covers, setCovers] = useState<Record<string, string>>({});

  // A real poster per theme — fetched once, best-effort (no cover → the tile falls back to its colour).
  useEffect(() => {
    let alive = true;
    fetch(`${API_BASE}/v1/categories/covers`)
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => {
        if (alive && d && d.covers) setCovers(d.covers as Record<string, string>);
      })
      .catch(() => {});
    return () => {
      alive = false;
    };
  }, []);

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
    <div className="onboard" role="dialog" aria-modal="true" aria-label="Соберём вашу афишу">
      <div className="onboard__sheet">
        <span className="onboard__kicker">ОКРЕСТ</span>
        <h2 className="onboard__title">соберём вашу афишу</h2>
        <p className="onboard__lede">
          Отметьте 3–5 тем — лента и подборки соберутся под вас. Поменять можно когда угодно.
        </p>

        <div className="onboard__cats" role="group" aria-label="Темы">
          {PICKABLE.map((c, i) => {
            const on = picked.includes(c.key);
            const cover = covers[c.key];
            return (
              <button
                key={c.key}
                type="button"
                className={`onboard__cat${on ? " onboard__cat--active" : ""}${cover ? " onboard__cat--photo" : ""}`}
                style={{ animationDelay: `${0.035 * i + 0.04}s`, ["--cat" as string]: c.color }}
                aria-pressed={on}
                onClick={() => toggle(c.key)}
              >
                {cover && <img className="onboard__catimg" src={cover} alt="" loading="lazy" decoding="async" />}
                <span className="onboard__catscrim" aria-hidden="true" />
                <span className="onboard__catrow">
                  <span className="onboard__caticon" aria-hidden="true">
                    <CategoryIcon cat={c.key} size={20} />
                  </span>
                  <span className="onboard__catlabel">{c.label}</span>
                </span>
                <span className="onboard__catcheck" aria-hidden="true">
                  ✓
                </span>
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
            {ready ? `Собрать афишу · ${picked.length} →` : `Выберите ещё ${left}`}
          </button>
          <button type="button" className="onboard__skip" onClick={() => onClose(picked)}>
            пропустить
          </button>
        </div>
      </div>
    </div>
  );
}
