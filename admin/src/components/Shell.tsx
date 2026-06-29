import { Outlet } from "react-router-dom";

import { useApi } from "../lib/useApi";
import { Sidebar } from "./Sidebar";

export function Shell() {
  // Лёгкий поллинг здоровья → бейдж-тревога на «Здоровье» в сайдбаре.
  const { data } = useApi<any>("/health", 60000);
  const warn = data ? data.stuck_runs > 0 || Object.values(data.deps || {}).some((v) => v !== "ok") : false;

  return (
    <div className="admin">
      <Sidebar healthWarn={warn} />
      <main className="main">
        <Outlet />
      </main>
    </div>
  );
}
