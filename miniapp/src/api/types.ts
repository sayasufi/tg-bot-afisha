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
  venue_id?: number | null; // for the venue page link (tap the place in the sheet)
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

// An active city the app serves (from GET /v1/cities → core.cities registry). Drives
// the city picker / auto-detect, per-city map centring, and the map `city` scope param.
export type City = { slug: string; name: string; lat: number; lon: number; radius_km: number };

export type EventDetail = {
  event_id: string;
  code?: string | null; // public "MSK-04PN" accession code
  canonical_title: string;
  canonical_description: string;
  category: string;
  subcategory: string;
  age_limit: string;
  primary_image_url: string;
  updated_at?: string | null; // last refresh — drives the "актуально на" trust line
  occurrences: EventOccurrence[];
};

// A venue page: the place + its upcoming events (events use the EventItem shape).
export type VenueDetail = {
  venue_id: number;
  name: string;
  address: string | null;
  lat: number | null;
  lon: number | null;
  open_now: boolean | null;
  hours_text: string | null;
  events: EventItem[];
};
