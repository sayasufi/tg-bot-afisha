import { NavLink } from "react-router-dom";

import { useAuth } from "../lib/auth";
import { NAV } from "../lib/nav";

export function Sidebar({ healthWarn }: { healthWarn?: boolean }) {
  const { user, logout } = useAuth();
  return (
    <aside className="sidebar">
      <div className="sidebar__brand">
        <div className="brand-word">
          <span className="o">о</span>крест
        </div>
        <div className="brand-kicker">// admin</div>
      </div>

      <nav className="nav">
        {NAV.map((g) => (
          <div className="navgroup" key={g.title}>
            <div className="navgroup__title">{g.title}</div>
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
        ))}
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
