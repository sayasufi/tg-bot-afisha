// Pull-to-refresh hint shown at the top of a scrollable panel. Translates and
// fades in with the pull distance; flips copy once armed or while refreshing.
export function PullHint({ pull, armed, refreshing }: { pull: number; armed: boolean; refreshing: boolean }) {
  const shown = refreshing || pull > 0;
  const label = refreshing ? "Обновляем…" : armed ? "Отпусти — обновлю" : "Потяни вниз";
  return (
    <div
      className={`pullhint${refreshing ? " pullhint--busy" : ""}`}
      aria-hidden={!shown}
      style={{
        height: refreshing ? 40 : pull,
        opacity: shown ? Math.min(1, pull / 48 || 1) : 0,
      }}
    >
      <span className={`pullhint__mark${armed || refreshing ? " pullhint__mark--on" : ""}`} />
      <span className="pullhint__label">{label}</span>
    </div>
  );
}
