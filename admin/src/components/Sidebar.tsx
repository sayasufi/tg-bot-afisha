import { ReactNode, useState } from "react";
import { NavLink, useLocation } from "react-router-dom";

import { useAuth } from "../lib/auth";
import { NAV } from "../lib/nav";

const ICONS: Record<string, ReactNode> = {
  Обзор: (
    <>
      <rect x="2" y="2" width="5" height="5" />
      <rect x="9" y="2" width="5" height="5" />
      <rect x="2" y="9" width="5" height="5" />
      <rect x="9" y="9" width="5" height="5" />
    </>
  ),
  Данные: (
    <>
      <rect x="2" y="3" width="12" height="2.5" />
      <rect x="2" y="7" width="12" height="2.5" />
      <rect x="2" y="11" width="12" height="2.5" />
    </>
  ),
  Ингест: (
    <>
      <path d="M8 2 v7" />
      <path d="M5 6 l3 3 3-3" />
      <path d="M3 13 h10" />
    </>
  ),
  Операции: (
    <>
      <path d="M2 4.5 h12 M2 8 h12 M2 11.5 h12" />
      <circle cx="5.5" cy="4.5" r="1.6" />
      <circle cx="10.5" cy="8" r="1.6" />
      <circle cx="6.5" cy="11.5" r="1.6" />
    </>
  ),
  Аудитория: (
    <>
      <circle cx="8" cy="5.5" r="2.5" />
      <path d="M3 13.5 a5 5 0 0 1 10 0" />
    </>
  ),
  Система: (
    <>
      <circle cx="8" cy="8" r="2.4" />
      <path d="M8 1.6v2 M8 12.4v2 M1.6 8h2 M12.4 8h2 M3.8 3.8l1.4 1.4 M10.8 10.8l1.4 1.4 M12.2 3.8l-1.4 1.4 M5.2 10.8l-1.4 1.4" />
    </>
  ),
};

function Icon({ name }: { name: string }) {
  return (
    <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round">
      {ICONS[name]}
    </svg>
  );
}

export function Sidebar({ healthWarn }: { healthWarn?: boolean }) {
  const { user, logout } = useAuth();
  const { pathname } = useLocation();

  const activeSection = NAV.find((g) => g.items.some((it) => it.to === pathname))?.title ?? NAV[0].title;
  const [open, setOpen] = useState<string>(activeSection);

  return (
    <aside className="sidebar">
      <div className="sidebar__brand">
        <div className="brand-word">
          <span className="o">о</span>крест
        </div>
        <div className="brand-kicker">// admin</div>
      </div>

      <nav className="nav">
        {NAV.map((g) => {
          const isOpen = open === g.title;
          const hasActive = g.items.some((it) => it.to === pathname);
          const warnHere = g.title === "Обзор" && healthWarn;
          return (
            <div className={"navsec" + (isOpen ? " navsec--open" : "")} key={g.title}>
              <button
                type="button"
                className={"navsec__head" + (hasActive ? " navsec__head--active" : "")}
                onClick={() => setOpen(isOpen ? "" : g.title)}
              >
                <span className="navsec__icon">
                  <Icon name={g.title} />
                </span>
                <span className="navsec__title">{g.title}</span>
                {warnHere && !isOpen && <span className="navsec__warn" />}
                <span className="navsec__chev">{isOpen ? "–" : "+"}</span>
              </button>

              {isOpen && (
                <div className="navsec__items">
                  {g.items.map((it) => (
                    <NavLink
                      key={it.to}
                      to={it.to}
                      end={it.to === "/"}
                      className={({ isActive }) =>
                        "navitem" + (isActive ? " navitem--active" : "") + (it.phase ? " navitem--soon" : "")
                      }
                    >
                      <span>{it.label}</span>
                      {it.phase ? (
                        <span className="navitem__soon">Ф{it.phase}</span>
                      ) : it.to === "/health" && healthWarn ? (
                        <span className="navitem__badge navitem__badge--warn">!</span>
                      ) : null}
                    </NavLink>
                  ))}
                </div>
              )}
            </div>
          );
        })}
      </nav>

      <div className="sidebar__foot">
        <div className="sidebar__user">
          <b>{user?.username ?? "admin"}</b>
          <span>владелец</span>
        </div>
        <button className="iconbtn" onClick={logout}>
          выход
        </button>
      </div>
    </aside>
  );
}
