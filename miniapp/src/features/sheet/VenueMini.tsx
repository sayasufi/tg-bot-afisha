import L from "leaflet";
import { MapContainer, Marker, TileLayer } from "react-leaflet";

// A small, non-interactive map of the venue point — orient yourself before you
// tap through to a full route. Carto's label-free positron keeps it in the
// white-cube key; our own acid pin is the only mark on it.
const pin = L.divIcon({
  className: "vmini-pin-wrap",
  html: '<span class="vmini-pin"></span>',
  iconSize: [18, 18],
  iconAnchor: [9, 9],
});

export function VenueMini({ lat, lon, href }: { lat: number; lon: number; href: string | null }) {
  const dark = document.documentElement.dataset.theme === "dark";
  const tiles = dark
    ? "https://{s}.basemaps.cartocdn.com/dark_nolabels/{z}/{x}/{y}{r}.png"
    : "https://{s}.basemaps.cartocdn.com/light_nolabels/{z}/{x}/{y}{r}.png";
  const open = () => {
    if (href) window.open(href, "_blank", "noopener,noreferrer");
  };
  return (
    <div className="vmini">
      <MapContainer
        center={[lat, lon]}
        zoom={15}
        zoomControl={false}
        attributionControl={false}
        dragging={false}
        scrollWheelZoom={false}
        doubleClickZoom={false}
        touchZoom={false}
        keyboard={false}
        boxZoom={false}
        style={{ height: "100%", width: "100%" }}
      >
        <TileLayer url={tiles} subdomains="abcd" maxZoom={19} />
        <Marker position={[lat, lon]} icon={pin} interactive={false} />
      </MapContainer>
      <span className="vmini__credit">© OSM · CARTO</span>
      {href && (
        <button type="button" className="vmini__hit" aria-label="Маршрут" onClick={open}>
          <span className="vmini__cta">Маршрут →</span>
        </button>
      )}
    </div>
  );
}
