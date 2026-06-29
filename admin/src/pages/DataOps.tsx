import { useState } from "react";

import { Badge, StatCard, fmtNum } from "../components/ui";
import { apiPost } from "../lib/api";
import { useApi } from "../lib/useApi";

const PIPELINE = /(normalize|enrich-candidates|dedup-candidates|reprocess|reindex|resolve-afisha)/;

export function DataOps() {
  const pipe = useApi<any>("/ops/pipeline", 30000);
  const flows = useApi<any>("/flows", 20000);
  const [busy, setBusy] = useState<Record<string, boolean>>({});

  const list = (flows.data?.flows ?? []).filter((f: any) => PIPELINE.test(f.name));
  const run = async (f: any) => {
    setBusy((b) => ({ ...b, [f.id]: true }));
    try { await apiPost("/ops/run", { deployment_id: f.id, name: f.name }); }
    finally { setTimeout(() => { setBusy((b) => ({ ...b, [f.id]: false })); flows.reload(); }, 1500); }
  };

  const funnel = pipe.data?.funnel ?? [];
  const runs = pipe.data?.runs;

  return (
    <div>
      <div className="page__head topbar">
        <div>
          <h1 className="page__title">обработка данных</h1>
          <div className="page__sub">воронка пайплайна: сырьё → кандидаты → события</div>
        </div>
        <button className="btn btn--ghost" onClick={() => { pipe.reload(); flows.reload(); }}>обновить</button>
      </div>

      {pipe.data && (
        <>
          <div className="statgrid">
            {funnel.map((s: any) => <StatCard key={s.stage} num={fmtNum(s.n)} label={s.stage} accent={s.stage === "события активные"} />)}
          </div>
          {runs && (
            <div className="bcast-note">
              Прогонов источников всего: <b>{fmtNum(runs.total)}</b> · сейчас идёт: <b>{runs.running}</b> ·
              ошибок за сутки: <b style={{ color: runs.failed_24h ? "var(--cinnabar)" : undefined }}>{runs.failed_24h}</b>.
            </div>
          )}
        </>
      )}

      <div className="section__title">запустить обработку вручную</div>
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
