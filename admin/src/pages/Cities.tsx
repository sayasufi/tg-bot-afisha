import { SortTh, useSort } from "../components/sortable";
import { Badge } from "../components/ui";
import { useApi } from "../lib/useApi";

type City = {
  slug: string; name: string; tz: string; utc_offset: number;
  venues: number; events: number; users: number; sources: string[]; has_telegram: boolean;
};

const SORT_GET = (c: City, k: string): any => {
  switch (k) {
    case "name": return c.name;
    case "utc": return c.utc_offset;
    case "events": return c.events;
    case "venues": return c.venues;
    case "users": return c.users;
    default: return c.name;
  }
};

export function Cities() {
  const { data, error, loading, reload } = useApi<{ items: City[] }>("/cities", 60000);
  const items = data?.items ?? [];
  const { sorted, sort, onSort } = useSort(items, SORT_GET, { key: "events", dir: "desc" });

  return (
    <div>
      <div className="page__head topbar">
        <div>
          <h1 className="page__title">города</h1>
          <div className="page__sub">{items.length} активных городов · реестр в коде, счётчики живые</div>
        </div>
        <button className="btn btn--ghost" onClick={reload}>обновить</button>
      </div>

      {loading && !data && <div className="state">загрузка…</div>}
      {error && <div className="state state--err">ошибка: {error}</div>}

      {data && (
        <div className="tablewrap">
          <table className="table">
            <thead>
              <tr>
                <SortTh label="город" k="name" sort={sort} onSort={onSort} />
                <SortTh label="UTC" k="utc" sort={sort} onSort={onSort} />
                <SortTh label="события" k="events" sort={sort} onSort={onSort} className="num" />
                <SortTh label="площадки" k="venues" sort={sort} onSort={onSort} className="num" />
                <SortTh label="юзеры" k="users" sort={sort} onSort={onSort} className="num" />
                <th>источники</th>
                <th>TG</th>
              </tr>
            </thead>
            <tbody>
              {sorted.map((c) => (
                <tr key={c.slug}>
                  <td>{c.name}<div className="code muted">{c.slug}</div></td>
                  <td className="muted">+{c.utc_offset}{c.utc_offset === 3 ? " (МСК)" : ""}</td>
                  <td className="num">{c.events.toLocaleString("ru-RU")}</td>
                  <td className="num muted">{c.venues.toLocaleString("ru-RU")}</td>
                  <td className="num muted">{c.users}</td>
                  <td style={{ display: "flex", gap: 4, flexWrap: "wrap" }}>
                    {c.sources.map((s) => <Badge key={s} kind="ok">{s}</Badge>)}
                  </td>
                  <td className="muted">{c.has_telegram ? "✓" : "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
