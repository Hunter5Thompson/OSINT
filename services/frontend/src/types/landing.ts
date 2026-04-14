/**
 * Landing summary — 24h hero numerals for the Landing page.
 *
 * Mirrors services/backend/app/models/landing.py.
 */

export interface LandingSummary {
  window: "24h";
  generated_at: string;

  hotspots_24h: number | null;
  hotspots_source: string;

  conflict_24h: number | null;
  conflict_source: string;

  nuntii_24h: number | null;
  nuntii_source: string;

  libri_24h: number;
  libri_source: string;
  reports_not_available_yet: boolean;
}
