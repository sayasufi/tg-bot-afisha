import { useState } from "react";

import type { City } from "../../api/client";
import { haptic } from "../../lib/telegram";

// Compact city picker — frosted chrome over the map, mirroring the command pill. Renders
// only when there's more than one active city (single-city deployments never see it).
export function CitySwitcher({
  cities,
  current,
  onSelect,
}: {
  cities: City[];
  current: City | null;
  onSelect: (slug: string) => void;
}) {
  const [open, setOpen] = useState(false);
  if (cities.length < 2 || !current) return null;

  return (
    <div className="cityswitch">
      <button
        type="button"
        className={`cityswitch__btn${open ? " is-open" : ""}`}
        aria-haspopup="listbox"
        aria-expanded={open}
        onClick={() => {
          haptic("light");
          setOpen((o) => !o);
        }}
      >
        <span className="cityswitch__name">{current.name}</span>
        <span className="cityswitch__chev" aria-hidden="true">
          {open ? "—" : "▾"}
        </span>
      </button>
      {open && (
        <>
          <button type="button" className="cityswitch__scrim" aria-label="Закрыть" onClick={() => setOpen(false)} />
          <ul className="cityswitch__menu" role="listbox">
            {cities.map((c) => (
              <li key={c.slug}>
                <button
                  type="button"
                  role="option"
                  aria-selected={c.slug === current.slug}
                  className={`cityswitch__opt${c.slug === current.slug ? " is-active" : ""}`}
                  onClick={() => {
                    haptic("light");
                    onSelect(c.slug);
                    setOpen(false);
                  }}
                >
                  {c.name}
                </button>
              </li>
            ))}
          </ul>
        </>
      )}
    </div>
  );
}
