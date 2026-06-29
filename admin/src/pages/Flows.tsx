import { useState } from "react";

import { Badge } from "../components/ui";
import { apiPost } from "../lib/api";
import { useApi } from "../lib/useApi";

const CATS = ["источники", "пайплайн", "обслуживание", "рассылки", "реклама"];

function category(name: string): string {
  if (name.startsWith("fetch-")) return "источники";
  if (/(normalize|enrich-candidates|dedup|reprocess|expire|self-heal)/.test(name)) return "пайплайн";
  if (/(discover|scrape|enrich-shortlist)/.test(name)) return "реклама";
  if (name.startsWith("send-")) return "рассылки";
  return "обслуживание";
}

function fmtSchedule(f: any): string {
  if (f.cron) return f.cron;
  if (f.interval) {
    const m = Math.round(f.interval / 60);
    if (m >= 1440) return `раз в ${Math.round(m / 1440)} дн`;
    if (m >= 60) return `каждые ${Math.round(m / 60)} ч`;
    return `каждые ${m} мин`;
  }
  return "—";
}

const STATE_KIND: Record<string, "ok" | "warn" | "down" | "off"> = {
  COMPLETED: "ok",
  RUNNING: "warn",
  PENDING: "warn",
  SCHEDULED: "warn",
  FAILED: "down",
  CRASHED: "down",
  CANCELLED: "off",
};
const STATE_LABEL: Record<string, string> = {
  COMPLETED: "успех",
  RUNNING: "идёт",
  PENDING: "ожидание",
  SCHEDULED: "в очереди",
  FAILED: "ошибка",
  CRASHED: "краш",
  CANCELLED: "отменён",
};

function ago(iso: string | null): string {
  if (!iso) return "—";
  const s = (Date.now() - new Date(iso).getTime()) / 1000;
  if (s < 60) return "только что";
  if (s < 3600) return `${Math.round(s / 60)} мин назад`;
  if (s < 86400) return `${Math.round(s / 3600)} ч назад`;
  return `${Math.round(s / 86400)} дн назад`;
}

function fmtRuntime(sec: number | null): string {
  if (sec == null) return "";
  if (sec < 60) return `${sec.toFixed(0)}с`;
  return `${Math.round(sec / 60)}м`;
}

export function Flows() {
  const { data, error, loading, reload } = useApi<any>("/flows", 20000);
  const runs = useApi<any>("/ops/runs", 20000);
  const [busy, setBusy] = useState<Record<string, boolean>>({});

  const run = async (f: any) => {
    setBusy((b) => ({ ...b, [f.id]: true }));
    try {
      await apiPost("/ops/run", { deployment_id: f.id, name: f.name });
      setTimeout(() => {
        reload();
        runs.reload();
      }, 1500);
    } catch {
      /* noop */
    } finally {
      setTimeout(() => setBusy((b) => ({ ...b, [f.id]: false })), 1500);
    }
  };

  const flows: any[] = data?.flows ?? [];
  const groups = CATS.map((cat) => ({ cat, items: flows.filter((f) => category(f.name) === cat) })).filter(
    (g) => g.items.length
  );

  return (
    <div>
      <div className="page__head topbar">
        <div>
          <h1 className="page__title">флоу</h1>
          <div className="page__sub">{flows.length} деплойментов · запуск вручную + расписание Prefect</div>
        </div>
        <button className="btn btn--ghost" onClick={reload}>обновить</button>
      </div>

      {loading && !data && <div className="state">загрузка…</div>}
      {error && <div className="state state--err">ошибка: {error}</div>}
      {data?.error && <div className="state state--err">{data.error}</div>}

      {groups.map((g) => (
        <div key={g.cat}>
          <div className="section__title">{g.cat}</div>
          <div className="tablewrap">
            <table className="table">
              <thead>
                <tr>
                  <th>флоу</th>
                  <th>расписание</th>
                  <th>последний прогон</th>
                  <th className="num">длит.</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {g.items.map((f) => (
                  <tr key={f.id}>
                    <td>
                      {f.name}
                      {f.paused && <span className="badge badge--off" style={{ marginLeft: 8 }}>пауза</span>}
                    </td>
                    <td className="muted">{fmtSchedule(f)}</td>
                    <td>
                      {f.last_state ? (
                        <span style={{ display: "inline-flex", gap: 8, alignItems: "center" }}>
                          <Badge kind={STATE_KIND[f.last_state] ?? "off"}>{STATE_LABEL[f.last_state] ?? f.last_state}</Badge>
                          <span className="muted">{ago(f.last_start)}</span>
                        </span>
                      ) : (
                        <span className="muted">— нет прогонов</span>
                      )}
                    </td>
                    <td className="num muted">{fmtRuntime(f.last_runtime)}</td>
                    <td style={{ textAlign: "right" }}>
                      <button className="iconbtn" onClick={() => run(f)} disabled={!!busy[f.id]}>
                        {busy[f.id] ? "…" : "запустить"}
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      ))}

      {runs.data?.runs?.length ? (
        <>
          <div className="section__title">последние прогоны</div>
          <div className="tablewrap">
            <table className="table">
              <thead>
                <tr>
                  <th>флоу</th>
                  <th>статус</th>
                  <th>когда</th>
                  <th className="num">длит.</th>
                </tr>
              </thead>
              <tbody>
                {runs.data.runs.map((r: any) => (
                  <tr key={r.id}>
                    <td>{r.flow}</td>
                    <td>
                      <Badge kind={STATE_KIND[r.state] ?? "off"}>{STATE_LABEL[r.state] ?? r.state}</Badge>
                    </td>
                    <td className="muted">{ago(r.start)}</td>
                    <td className="num muted">{fmtRuntime(r.runtime)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      ) : null}
    </div>
  );
}
