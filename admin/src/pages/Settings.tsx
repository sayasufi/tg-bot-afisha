import { useState } from "react";

import { Badge } from "../components/ui";
import { apiDelete, apiPost } from "../lib/api";
import { useApi } from "../lib/useApi";

type Setting = {
  key: string;
  type: "bool" | "int" | "float";
  label: string;
  group: string;
  hint: string;
  default: any;
  value: any;
  source: "env" | "override";
};

export function Settings() {
  const { data, loading, error, reload } = useApi<{ items: Setting[] }>("/settings", 30000);
  const items = data?.items ?? [];
  const [busy, setBusy] = useState<Record<string, boolean>>({});

  const groups = [...new Set(items.map((s) => s.group))];

  const setVal = async (s: Setting, value: any) => {
    setBusy((b) => ({ ...b, [s.key]: true }));
    try {
      await apiPost(`/settings/${s.key}`, { value });
      reload();
    } finally {
      setTimeout(() => setBusy((b) => ({ ...b, [s.key]: false })), 300);
    }
  };

  const reset = async (s: Setting) => {
    setBusy((b) => ({ ...b, [s.key]: true }));
    try {
      await apiDelete(`/settings/${s.key}`);
      reload();
    } finally {
      setTimeout(() => setBusy((b) => ({ ...b, [s.key]: false })), 300);
    }
  };

  return (
    <div>
      <div className="page__head topbar">
        <div>
          <h1 className="page__title">настройки</h1>
          <div className="page__sub">живые тогглы — действуют без рестарта (в течение ~15 с)</div>
        </div>
        <button className="btn btn--ghost" onClick={reload}>обновить</button>
      </div>

      {loading && !data && <div className="state">загрузка…</div>}
      {error && <div className="state state--err">ошибка: {error}</div>}

      {data &&
        groups.map((g) => (
          <section key={g}>
            <div className="section__title">{g}</div>
            <div className="tablewrap">
              <table className="table">
                <tbody>
                  {items
                    .filter((s) => s.group === g)
                    .map((s) => (
                      <tr key={s.key}>
                        <td>
                          <div>{s.label}</div>
                          <div className="chart-hint" style={{ margin: "2px 0 0" }}>{s.hint}</div>
                          <div className="code muted">{s.key}</div>
                        </td>
                        <td>
                          {s.type === "bool" ? (
                            <button className="iconbtn" disabled={!!busy[s.key]} onClick={() => setVal(s, !s.value)} title={s.value ? "выключить" : "включить"}>
                              {s.value ? <Badge kind="ok">вкл</Badge> : <Badge kind="off">выкл</Badge>}
                            </button>
                          ) : (
                            <input
                              type="number"
                              key={`${s.key}-${String(s.value)}`}
                              defaultValue={s.value}
                              disabled={!!busy[s.key]}
                              style={{ width: 90 }}
                              onBlur={(e) => {
                                const v = s.type === "int" ? parseInt(e.target.value, 10) : parseFloat(e.target.value);
                                if (!Number.isNaN(v) && v !== s.value) setVal(s, v);
                              }}
                            />
                          )}
                        </td>
                        <td>
                          {s.source === "override" ? <Badge kind="warn">переопределено</Badge> : <span className="muted">из env</span>}
                        </td>
                        <td className="muted">по умолчанию: {String(s.default)}</td>
                        <td style={{ textAlign: "right" }}>
                          <button className="iconbtn" disabled={!!busy[s.key] || s.source === "env"} onClick={() => reset(s)} title="вернуть значение из env">
                            сбросить
                          </button>
                        </td>
                      </tr>
                    ))}
                </tbody>
              </table>
            </div>
          </section>
        ))}
    </div>
  );
}
