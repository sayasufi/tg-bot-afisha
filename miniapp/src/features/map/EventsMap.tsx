import { MapContainer, Marker, Popup, TileLayer } from "react-leaflet";

import type { EventItem } from "../../api/client";

type Props = {
  items: EventItem[];
  onSelect: (item: EventItem) => void;
};

export function EventsMap({ items, onSelect }: Props) {
  return (
    <div className="map-wrap">
      <MapContainer center={[55.751244, 37.618423]} zoom={11} style={{ height: "100%", width: "100%" }}>
        <TileLayer url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png" attribution="&copy; OpenStreetMap contributors" />
        {items
          .filter((item) => item.lat !== null && item.lon !== null)
          .map((item) => (
            <Marker key={item.event_id} position={[item.lat as number, item.lon as number]} eventHandlers={{ click: () => onSelect(item) }}>
              <Popup>
                <strong>{item.title}</strong>
                <br />
                {item.date_start}
              </Popup>
            </Marker>
          ))}
      </MapContainer>
    </div>
  );
}
