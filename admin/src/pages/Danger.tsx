import { useState } from "react";

import { Badge } from "../components/ui";
import { apiPost } from "../lib/api";
import { useMutate } from "../lib/mutate";
import { useApi } from "../lib/useApi";

// Тяжёлые/перестраивающие процессы — запуск с подтверждением.
const DANGER = /(self-heal|merge-duplicate|expire-past|backfill|prune-telegram|sweep-stale|reindex-search)/;

export function Danger() {
  const flows = useApi<any>("/flows", 20000);
  const [busy, setBusy] = useState<Record<string, boolean>>({});
  const mutate = useMutate();

  const list = (flows.data?.flows ?? []).filter((f: any) => DANGER.test(f.name));
  const run = async (f: any) => {
    if (!window.confirm(`Запустить «${f.name}»? Это тяжёлый процесс — он меняет/перестраивает данные.`)) return;
    setBusy((b) => ({ ...b, [f.id]: true }));
    try { await mutate(() => apiPost("/ops/run", { deployment_id: f.id, name: f.name }), "процесс запущен"); }
    finally { setTimeout(() => { setBusy((b) => ({ ...b, [f.id]: false })); flows.reload(); }, 1500); }
  };

  return (
    <div>
      <div className="page__head topbar">
        <div>
          <h1 className="page__title">опасная зона</h1>
          <div className="page__sub">тяжёлые операции обслуживания — с подтверждением</div>
        </div>
        <button className="btn btn--ghost" onClick={flows.reload}>обновить</button>
      </div>

      <div className="bcast-note">
        Процессы ниже перестраивают данные (слияние дублей, чистка прошедших, переиндексация, бэкфилл).
        Они идемпотентны и идут по расписанию сами — ручной запуск нужен лишь точечно. Каждый запуск
        пишется в <span className="code">журнал действий</span>.
      </div>

      {flows.error && <div className="state state--err">{flows.error}</div>}
      <div className="tablewrap">
        <table className="table">
          <thead><tr><th>процесс</th><th>последний прогон</th><th /></tr></thead>
          <tbody>
            {list.map((f: any) => (
              <tr key={f.id}>
                <td>{f.name}</td>
                <td className="muted">{f.last_state ? <Badge kind={f.last_state === "COMPLETED" ? "ok" : f.last_state === "FAILED" ? "down" : "warn"}>{f.last_state}</Badge> : "— нет"}</td>
                <td style={{ textAlign: "right" }}>
                  <button className="iconbtn" disabled={!!busy[f.id]} onClick={() => run(f)}>{busy[f.id] ? "…" : "запустить"}</button>
                </td>
              </tr>
            ))}
            {!list.length && <tr><td colSpan={3} className="muted">{flows.loading ? "загрузка процессов…" : "нет процессов"}</td></tr>}
          </tbody>
        </table>
      </div>
    </div>
  );
}
