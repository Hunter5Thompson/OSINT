/**
 * LandingPage · Astrolabe (Hlíðskjalf §4.1).
 *
 * Wires the four hero numerals (Hotspots / Conflictus / Nuntii / Libri)
 * to `/api/landing/summary?window=24h`, the Signal Feed to
 * `useSignalFeed()` (SSE + /api/signals/latest hydration), and clicks to
 * the Worldview deep-link filters.
 *
 * Ships in ODIN S1 Task 6. Visual polish (grain overlay, staggered reveal
 * animation) lands in Task 7.
 */
import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { NumericHero } from "../components/hlidskjalf/NumericHero";
import type { NumericAccent } from "../components/hlidskjalf/NumericHero";
import { Orrery } from "../components/hlidskjalf/Orrery";
import { SectionHeading } from "../components/hlidskjalf/SectionHeading";
import { SignalFeedItem } from "../components/hlidskjalf/SignalFeedItem";
import type { SignalSeverity as FeedSeverity } from "../components/hlidskjalf/SignalFeedItem";
import { useSignalFeed } from "../hooks/useSignalFeed";
import { getLandingSummary } from "../services/api";
import type { LandingSummary } from "../types/landing";
import type { SignalEnvelope, SignalSeverity } from "../types/signals";

type FilterKey = "hotspots" | "conflict" | "nuntii" | "libri";

const SEVERITY_MAP: Record<SignalSeverity, FeedSeverity> = {
  critical: "sent",
  high: "amb",
  medium: "sage",
  low: "dim",
};

function mapSeverity(sev?: string): FeedSeverity {
  if (sev && sev in SEVERITY_MAP) return SEVERITY_MAP[sev as SignalSeverity];
  return "dim";
}

function formatTime(iso: string): string {
  try {
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return "--:--Z";
    const hh = String(d.getUTCHours()).padStart(2, "0");
    const mm = String(d.getUTCMinutes()).padStart(2, "0");
    return `${hh}:${mm}Z`;
  } catch {
    return "--:--Z";
  }
}

function entityParam(env: SignalEnvelope): string {
  const { payload } = env;
  const source = (payload.source || env.type.replace(/^signal\./, "")).trim() || "signal";
  const id = payload.redis_id || env.event_id;
  return `${source}:${id}`;
}

interface TileSpec {
  key: FilterKey;
  label: string;
  accent: NumericAccent;
  value: number | null;
  source: string;
  forceZero?: boolean;
  pendingLabel?: string;
}

function tileValueDisplay(spec: TileSpec): {
  display: string | number;
  subLabel: string | undefined;
} {
  if (spec.forceZero) {
    return { display: 0, subLabel: spec.pendingLabel };
  }
  if (spec.value === null || spec.value === undefined) {
    return { display: "—", subLabel: `source:${spec.source}` };
  }
  return { display: spec.value, subLabel: undefined };
}

export function LandingPage() {
  const navigate = useNavigate();
  const [summary, setSummary] = useState<LandingSummary | null>(null);
  const [summaryError, setSummaryError] = useState<string | null>(null);
  const { items: feedItems } = useSignalFeed();

  useEffect(() => {
    let active = true;
    getLandingSummary("24h")
      .then((s) => {
        if (active) setSummary(s);
      })
      .catch((err: unknown) => {
        if (!active) return;
        setSummaryError(err instanceof Error ? err.message : String(err));
      });
    return () => {
      active = false;
    };
  }, []);

  const tiles = useMemo<TileSpec[]>(() => {
    return [
      {
        key: "hotspots",
        label: "Hotspots",
        accent: "sent",
        value: summary?.hotspots_24h ?? null,
        source: summary?.hotspots_source ?? "unavailable",
      },
      {
        key: "conflict",
        label: "Conflictus",
        accent: "amber",
        value: summary?.conflict_24h ?? null,
        source: summary?.conflict_source ?? "unavailable",
      },
      {
        key: "nuntii",
        label: "Nuntii",
        accent: "sage",
        value: summary?.nuntii_24h ?? null,
        source: summary?.nuntii_source ?? "unavailable",
      },
      {
        key: "libri",
        label: "Libri",
        accent: "parchment",
        value: summary?.libri_24h ?? 0,
        source: summary?.libri_source ?? "reports",
        forceZero: summary?.reports_not_available_yet ?? true,
        pendingLabel: "pending · S3",
      },
    ];
  }, [summary]);

  const handleTileClick = (key: FilterKey) => {
    navigate(`/worldview?filter=${key}`);
  };

  const handleFeedClick = (env: SignalEnvelope) => {
    navigate(`/worldview?entity=${encodeURIComponent(entityParam(env))}`);
  };

  return (
    <div
      data-page="landing"
      style={{
        flex: 1,
        display: "flex",
        flexDirection: "column",
        padding: "2rem 2.5rem",
        gap: "2rem",
      }}
    >
      <header style={{ display: "flex", alignItems: "baseline", justifyContent: "space-between" }}>
        <SectionHeading label="Index Rerum · last 24h" />
        <span className="mono" style={{ color: "var(--ash)", fontSize: "0.75rem" }}>
          {summaryError ? `err · ${summaryError}` : summary ? "live" : "loading"}
        </span>
      </header>

      <section
        data-part="numerals"
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(4, minmax(0, 1fr))",
          gap: "1.5rem",
        }}
      >
        {tiles.map((tile) => {
          const { display, subLabel } = tileValueDisplay(tile);
          return (
            <button
              key={tile.key}
              type="button"
              data-tile={tile.key}
              aria-label={tile.label}
              onClick={() => handleTileClick(tile.key)}
              style={{
                background: "transparent",
                border: "none",
                borderTop: "1px solid var(--granite)",
                padding: "1rem 0 0 0",
                textAlign: "left",
                cursor: "pointer",
                color: "inherit",
              }}
            >
              <NumericHero
                value={display}
                label={tile.label}
                accent={tile.accent}
                sub={subLabel}
              />
            </button>
          );
        })}
      </section>

      <hr className="hair" style={{ border: 0, borderTop: "1px solid var(--granite)" }} />

      <section
        data-part="feed-and-orrery"
        style={{
          display: "grid",
          gridTemplateColumns: "1fr auto",
          gap: "2rem",
          alignItems: "start",
        }}
      >
        <div>
          <SectionHeading label="Signal Feed · live" />
          <div data-part="signal-feed" style={{ marginTop: "0.75rem" }}>
            {feedItems.length === 0 ? (
              <span style={{ color: "var(--ash)", fontSize: "0.85rem" }}>
                — no signals yet —
              </span>
            ) : (
              feedItems.map((env) => (
                <SignalFeedItem
                  key={env.event_id}
                  severity={mapSeverity(env.payload.severity)}
                  ts={formatTime(env.ts)}
                  text={env.payload.title || env.type}
                  onClick={() => handleFeedClick(env)}
                />
              ))
            )}
          </div>
        </div>
        <div data-part="orrery-anchor">
          <Orrery size="m" />
        </div>
      </section>
    </div>
  );
}
