export function BarChart({ data }: { data: { label: string; value: number }[] }) {
  if (!data || !data.length) return <div className="state">нет данных за период</div>;
  const max = Math.max(1, ...data.map((d) => d.value));
  return (
    <div className="barchart">
      {data.map((d, i) => (
        <div className="barchart__col" key={i} title={`${d.label}: ${d.value}`}>
          <div className="barchart__track">
            <div
              className={"barchart__bar" + (i === data.length - 1 ? " barchart__bar--last" : "")}
              style={{ height: `${Math.max(2, (d.value / max) * 100)}%` }}
            />
          </div>
          <div className="barchart__label">{d.label}</div>
        </div>
      ))}
    </div>
  );
}
