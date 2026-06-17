// Barrel for the API layer — keeps `../api/client` imports working after the
// split into types / http / events / users modules.
export type { EventItem, EventOccurrence, EventDetail, MapResponse, MapCluster, City } from "./types";
export { fetchMapEvents, fetchNearby, fetchEventDetail, fetchMetro, fetchCities, searchEvents, type MetroStation } from "./events";
export { saveUserLocation } from "./users";
export { prepareShare } from "./share";
