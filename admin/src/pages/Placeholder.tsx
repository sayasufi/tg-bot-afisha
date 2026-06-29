import { useLocation } from "react-router-dom";

import { ALL_ITEMS } from "../lib/nav";

export function Placeholder() {
  const { pathname } = useLocation();
  const item = ALL_ITEMS.find((i) => i.to === pathname);
  const title = item?.label ?? "раздел";
  const phase = item?.phase;
  return (
    <div>
      <div className="page__head">
        <h1 className="page__title">{title.toLowerCase()}</h1>
      </div>
      <div className="placeholder">
        <h2>раздел в разработке</h2>
        <p>Здесь появятся данные и управление этим разделом.</p>
        {phase && <div className="phase-pill">запланировано · фаза {phase}</div>}
      </div>
    </div>
  );
}
