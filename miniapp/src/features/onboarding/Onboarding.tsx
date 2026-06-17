import { IconHeart, IconSearch } from "../../lib/icons";

// One-time first-run guide — a VITRINE "exhibition handout" that tells a new visitor
// what the app is and WHERE the hidden bits live (search, filter, and the sections
// behind ☰). Shown over the loaded map after the splash lifts; dismissed forever.
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

export function Onboarding({ onClose }: { onClose: () => void }) {
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
        <button type="button" className="onboard__cta" onClick={onClose}>
          Понятно
        </button>
      </div>
    </div>
  );
}
