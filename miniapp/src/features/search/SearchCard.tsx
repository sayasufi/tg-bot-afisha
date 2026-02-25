import type { EventItem } from "../../api/client";

type Props = {
  selected: EventItem | null;
};

export function SearchCard({ selected }: Props) {
  if (!selected) {
    return null;
  }
  return (
    <div className="card">
      <h3>{selected.title}</h3>
      <p>{selected.category}</p>
      <p>{new Date(selected.date_start).toLocaleString()}</p>
      <p>{selected.venue || "Unknown venue"}</p>
      <p>{selected.price_min ? `${selected.price_min} RUB` : "Цена не указана"}</p>
    </div>
  );
}
