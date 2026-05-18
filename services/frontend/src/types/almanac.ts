export interface AlmanacCapital {
  name: string;
  lat: number;
  lon: number;
}

export interface AlmanacFact {
  label: string;
  value: string;
}

export interface AlmanacFacts {
  profile: AlmanacFact[];
  people: AlmanacFact[];
  government: AlmanacFact[];
  economy: AlmanacFact[];
  security: AlmanacFact[];
}

export interface CountryAlmanac {
  id: string;
  iso3: string | null;
  m49: string;
  name: string;
  region: string;
  subregion: string;
  capital: AlmanacCapital | null;
  facts: AlmanacFacts;
  updated_at: string;
  source_note: string;
}

export interface AlmanacSignalItem {
  event_id: string;
  ts: string;
  type: string;
  title: string;
  severity: string;
  source: string;
  url: string;
}

export interface AlmanacSignalResponse {
  country_id: string;
  items: AlmanacSignalItem[];
}
