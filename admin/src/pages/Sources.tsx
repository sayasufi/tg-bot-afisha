import { useMemo, useState } from "react";

import { Badge } from "../components/ui";
import { apiPost } from "../lib/api";
import { useApi } from "../lib/useApi";

type Source = {
  source_id: number;
  name: string;
  kind: string;
  is_active: boolean;
  crawl_interval_sec: number;
  last_status: string | null;
  last_finished: string | null;
};

const STATUS_KIND: Record<string, "ok" | "warn" | "down" | "off"> = {
  success: "ok",
  running: "warn",
  pending: "warn",
  failed: "down",
  error: "down",
};
const STATUS_LABEL: Record<string, string> = {
  success: "успех",
  running: "идёт",
  pending: "ожидание",
  failed: "ошибка",
  error: "ошибка",
};

function ago(iso: string | null): string {
  if (!iso) return "—";
  const s = (Date.now() - new Date(iso).getTime()) / 1000;
  if (s < 60) return "только что";
  if (s < 3600) return `${Math.round(s / 60)} мин назад`;
  if (s < 86400) return `${Math.round(s / 3600)} ч назад`;
  return `${Math.round(s / 86400)} дн назад`;
}

function fmtInterval(sec: number): string {
  if (sec >= 86400) return `${Math.round(sec / 86400)} дн`;
  if (sec >= 3600) return `${Math.round(sec / 3600)} ч`;
  if (sec >= 60) return `${Math.round(sec / 60)} мин`;
  return `${sec} с`;
}

export function Sources() {
  const [q, setQ] = useState("");
  const [kind, setKind] = useState("");
  const [active, setActive] = useState("");

  // q здесь применяется на клиенте поверх загруженных 300 строк; kind/active гоним на сервер
  // (их немного, фильтр-выборка точна). Для серверного q меняем path → useApi перезагрузится.
  const path = useMemo(() => {
    const p = new URLSearchParams();
    if (q.trim()) p.set("q", q.trim());
    if (kind) p.set("kind", kind);
    if (active) p.set("active", active);
    const s = p.toString();
    return s ? `/sources?${s}` : "/sources";
  }, [q, kind, active]);

  const { data, error, loading, reload } = useApi<{ items: Source[]; total: number; shown: number }>(path);
  const [busy, setBusy] = useState<Record<number, boolean>>({});
  const [draft, setDraft] = useState<Record<number, string>>({});

  const setBusyFor = (id: number, v: boolean) => setBusy((b) => ({ ...b, [id]: v }));

  const toggle = async (s: Source) => {
    setBusyFor(s.source_id, true);
    try {
      await apiPost(`/sources/${s.source_id}/toggle`, { active: !s.is_active });
      reload();
    } finally {
      setBusyFor(s.source_id, false);
    }
  };

  const saveInterval = async (s: Source) => {
    const raw = draft[s.source_id] ?? String(s.crawl_interval_sec);
    const sec = parseInt(raw, 10);
    if (!Number.isFinite(sec) || sec < 60) return;
    setBusyFor(s.source_id, true);
    try {
      await apiPost(`/sources/${s.source_id}/interval`, { sec });
      setDraft((d) => {
        const next = { ...d };
        delete next[s.source_id];
        return next;
      });
      reload();
    } finally {
      setBusyFor(s.source_id, false);
    }
  };

  const items = data?.items ?? [];

  return (
    <div>
      <div className="page__head topbar">
        <div>
          <h1 className="page__title">источники</h1>
          <div className="page__sub">
            {data ? `${data.total} источников · показано ${data.shown}` : "источники ингеста · тоглы и интервал"}
          </div>
        </div>
        <button className="btn btn--ghost" onClick={reload}>обновить</button>
      </div>

      <div className="topbar" style={{ gap: 8, marginBottom: 16, flexWrap: "wrap" }}>
        <input
          className="login__input"
          placeholder="поиск по имени…"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          style={{ minWidth: 220 }}
        />
        <select className="login__input" value={kind} onChange={(e) => setKind(e.target.value)}>
          <option value="">все типы</option>
          <option value="telegram">telegram</option>
          <option value="web">web</option>
        </select>
        <select className="login__input" value={active} onChange={(e) => setActive(e.target.value)}>
          <option value="">все статусы</option>
          <option value="true">активные</option>
          <option value="false">выключенные</option>
        </select>
      </div>

      {loading && !data && <div className="state">загрузка…</div>}
      {error && <div className="state state--err">ошибка: {error}</div>}

      {data && (
        <div className="tablewrap">
          <table className="table">
            <thead>
              <tr>
                <th>источник</th>
                <th>тип</th>
                <th>активен</th>
                <th>интервал</th>
                <th>последний прогон</th>
              </tr>
            </thead>
            <tbody>
              {items.map((s) => {
                const dv = draft[s.source_id] ?? String(s.crawl_interval_sec);
                const changed = dv !== String(s.crawl_interval_sec);
                return (
                  <tr key={s.source_id}>
                    <td className="code">{s.name}</td>
                    <td className="muted">{s.kind}</td>
                    <td>
                      <button
                        className="iconbtn"
                        disabled={!!busy[s.source_id]}
                        onClick={() => toggle(s)}
                        title={s.is_active ? "выключить" : "включить"}
                      >
                        {s.is_active ? <Badge kind="ok">вкл</Badge> : <Badge kind="off">выкл</Badge>}
                      </button>
                    </td>
                    <td className="muted" title="расписание задаётся в Prefect (вкладка Флоу); это поле информативно">
                      {fmtInterval(s.crawl_interval_sec)}
                    </td>
                    <td>
                      {s.last_status ? (
                        <span style={{ display: "inline-flex", gap: 8, alignItems: "center" }}>
                          <Badge kind={STATUS_KIND[s.last_status] ?? "off"}>
                            {STATUS_LABEL[s.last_status] ?? s.last_status}
                          </Badge>
                          <span className="muted">{ago(s.last_finished)}</span>
                        </span>
                      ) : (
                        <span className="muted">— нет прогонов</span>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
