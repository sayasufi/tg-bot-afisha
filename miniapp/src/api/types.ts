export type EventItem = {
  event_id: string;
  code?: string | null; // public "MSK-04PN" accession code
  title: string;
  category: string;
  date_start: string;
  date_end: string | null;
  price_min: number | null;
  venue: string | null;
  // Compact "open now" tri-state computed server-side in Moscow time (true/false/null
  // unknown) — replaces the full weekly schedule on the map payload. Full venue_hours
  // live on the detail endpoint (EventOccurrence below). Drives the "идёт сейчас" badge.
  open_now?: boolean | null;
  lat: number | null;
  lon: number | null;
  primary_image_url?: string | null;
};

// A server-side aggregated cluster: a single point standing in for `count`
// events, returned at low zoom so the map payload/marker count don't grow with
// the total number of events.
export type MapCluster = { id: string; lat: number; lon: number; count: number };

export type MapResponse = {
  clusters: MapCluster[];
  items: EventItem[];
  total: number;
};

export type EventOccurrence = {
  occurrence_id: number;
  date_start: string;
  date_end: string | null;
  price_min: number | null;
  price_max: number | null;
  currency: string;
  source_best_url: string;
  venue: string | null;
  address: string | null;
  venue_hours: VenueHours | null;
  lat: number | null;
  lon: number | null;
};

// Opening hours: week[d] is a list of ["HH:MM","HH:MM"] ranges or null (closed),
// index 0=Sunday (JS getDay). `text` is the human label.
export type VenueHours = { text?: string; week?: (string[][] | null)[] };

export type EventDetail = {
  event_id: string;
  code?: string | null; // public "MSK-04PN" accession code
  canonical_title: string;
  canonical_description: string;
  category: string;
  subcategory: string;
  age_limit: string;
  primary_image_url: string;
  occurrences: EventOccurrence[];
};
