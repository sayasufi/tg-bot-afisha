export type EventItem = {
  event_id: string;
  title: string;
  category: string;
  date_start: string;
  date_end: string | null;
  price_min: number | null;
  venue: string | null;
  lat: number | null;
  lon: number | null;
  primary_image_url?: string | null;
};

export type MapResponse = {
  clusters: Array<{ id: string; lat: number; lon: number; count: number }>;
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
  lat: number | null;
  lon: number | null;
};

export type EventDetail = {
  event_id: string;
  canonical_title: string;
  canonical_description: string;
  category: string;
  subcategory: string;
  age_limit: string;
  primary_image_url: string;
  occurrences: EventOccurrence[];
};
