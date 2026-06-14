// Barrel for the API layer — keeps `../api/client` imports working after the
// split into types / http / events / users modules.
export type { EventItem, EventOccurrence, EventDetail, MapResponse } from "./types";
export { fetchMapEvents, fetchNearby, fetchEventDetail } from "./events";
export { saveUserLocation } from "./users";
