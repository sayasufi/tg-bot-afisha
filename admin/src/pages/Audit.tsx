import { useEffect, useMemo, useState } from "react";

import { useApi } from "../lib/useApi";

type Row = {
  actor: string; action: string; target: string | null;
  params: Record<string, any> | null; result: string | null; ip: string | null; created_at: string | null;
};

function when(iso: string | null): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleString("ru-RU", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
}

export function Audit() {
  const facets = useApi<{ actions: string[] }>("/audit/facets");
  const [action, setAction] = useState("");
  const [page, setPage] = useState(0);

  const path = useMemo(() => {
    const p = new URLSearchParams();
    if (action) p.set("action", action);
    if (page) p.set("page", String(page));
    return `/audit?${p.toString()}`;
  }, [action, page]);

  const { data, error, loading, reload } = useApi<any>(path, 20000);
  const items: Row[] = data?.items ?? [];
  const total = data?.total ?? 0;
  const pages = Math.max(1, Math.ceil(total / (data?.page_size ?? 100)));

  useEffect(() => { setPage(0); }, [action]);

  return (
    <div>
      <div className="page__head topbar">
        <div>
          <h1 className="page__title">журнал действий</h1>
          <div className="page__sub">{data ? `${total} записей` : "все изменения через админку"}</div>
        </div>
        <button className="btn btn--ghost" onClick={reload}>обновить</button>
      </div>

      <div className="filterbar">
        <select value={action} onChange={(e) => setAction(e.target.value)}>
          <option value="">все действия</option>
          {(facets.data?.actions ?? []).map((a) => <option key={a} value={a}>{a}</option>)}
        </select>
        <span className="filter-count">{loading ? "…" : `показано ${items.length}`}</span>
      </div>

      {error && <div className="state state--err">ошибка: {error}</div>}
      {loading && !data && <div className="state">загрузка…</div>}

      {data && (
        <>
          <div className="tablewrap">
            <table className="table">
              <thead>
                <tr><th>время</th><th>кто</th><th>действие</th><th>объект</th><th>детали</th><th>IP</th></tr>
              </thead>
              <tbody>
                {items.map((r, i) => (
                  <tr key={i}>
                    <td className="muted">{when(r.created_at)}</td>
                    <td>{r.actor}</td>
                    <td className="code">{r.action}{r.result && r.result !== "ok" ? ` · ${r.result}` : ""}</td>
                    <td className="muted code">{r.target ? r.target.slice(0, 18) : "—"}</td>
                    <td className="muted" style={{ maxWidth: 280, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                      {r.params ? JSON.stringify(r.params) : "—"}
                    </td>
                    <td className="muted code">{r.ip ?? "—"}</td>
                  </tr>
                ))}
                {!items.length && <tr><td colSpan={6} className="muted">пока пусто</td></tr>}
              </tbody>
            </table>
          </div>
          <div className="pager">
            <button className="iconbtn" disabled={page <= 0} onClick={() => setPage((p) => Math.max(0, p - 1))}>← назад</button>
            <span className="filter-count" style={{ margin: 0 }}>стр {page + 1} из {pages}</span>
            <button className="iconbtn" disabled={page >= pages - 1} onClick={() => setPage((p) => p + 1)}>вперёд →</button>
          </div>
        </>
      )}
    </div>
  );
}
