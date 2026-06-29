import { IngestTable } from "../components/IngestTable";
import { Dot, StatCard } from "../components/ui";
import { useApi } from "../lib/useApi";

const DEP_LABELS: Record<string, string> = {
  postgres: "PostgreSQL",
  redis: "Redis",
  meili: "Meilisearch",
  minio: "MinIO",
};

export function Health() {
  const { data, error, loading, reload } = useApi<any>("/health", 30000);

  return (
    <div>
      <div className="page__head topbar">
        <div>
          <h1 className="page__title">здоровье</h1>
          {data && <div className="page__sub page__meta">обновлено {new Date(data.as_of).toLocaleString("ru-RU")}</div>}
        </div>
        <button className="btn btn--ghost" onClick={reload}>обновить</button>
      </div>

      {loading && !data && <div className="state">загрузка…</div>}
      {error && <div className="state state--err">ошибка: {error}</div>}

      {data && (
        <>
          <div className="section__title">зависимости</div>
          <div className="statgrid">
            {Object.entries(data.deps as Record<string, string>).map(([dep, st]) => (
              <StatCard
                key={dep}
                num={
                  <span style={{ display: "inline-flex", alignItems: "center", gap: 10 }}>
                    <Dot kind={st === "ok" ? "ok" : st === "degraded" ? "warn" : "down"} />
                    <span style={{ fontSize: 18, textTransform: "uppercase", fontFamily: "var(--mono)" }}>{st}</span>
                  </span>
                }
                label={DEP_LABELS[dep] ?? dep}
              />
            ))}
            <StatCard
              num={data.stuck_runs}
              label="зависших прогонов"
              tone={data.stuck_runs > 0 ? "warn" : undefined}
              sub="status=running >2ч"
            />
          </div>

          <div className="section__title">ингест по источникам</div>
          <IngestTable rows={data.ingest} />
        </>
      )}
    </div>
  );
}
