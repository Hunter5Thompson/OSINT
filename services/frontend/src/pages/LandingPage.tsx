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
import { Link, useNavigate } from "react-router-dom";
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

const INTRO_ACTIONS = [
  { to: "/worldview", label: "Enter Worldview" },
  { to: "/briefing", label: "Open Briefing" },
  { to: "/warroom", label: "War Room" },
] as const;

const CAPABILITIES = [
  { label: "Hugin", detail: "ingestion pipeline" },
  { label: "Signalia", detail: "Signal Feed / SSE" },
  { label: "Vectorium", detail: "Qdrant vector search" },
  { label: "Memoria", detail: "Neo4j graph memory" },
  { label: "Fenestra", detail: "24h landing window" },
] as const;

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

function LandingIntro() {
  return (
    <section
      data-part="landing-intro"
      style={{
        display: "grid",
        gridTemplateColumns: "repeat(auto-fit, minmax(min(100%, 18rem), 1fr))",
        gap: "2rem",
        alignItems: "stretch",
        paddingBottom: "2rem",
        borderBottom: "1px solid var(--granite)",
      }}
    >
      <div style={{ display: "flex", flexDirection: "column", justifyContent: "center" }}>
        <span className="eyebrow">ODIN · Hlíðskjalf</span>
        <h1
          className="serif"
          style={{
            margin: "0.65rem 0 1rem",
            maxWidth: "46rem",
            color: "var(--parchment)",
            fontSize: "clamp(3rem, 6vw, 5.75rem)",
            lineHeight: 0.95,
            fontWeight: 400,
          }}
        >
          See the operating picture before it becomes a report.
        </h1>
        <p
          style={{
            maxWidth: "42rem",
            margin: 0,
            color: "var(--bone)",
            fontSize: "1rem",
            lineHeight: 1.65,
          }}
        >
          ODIN fuses live signals, infrastructure layers, incident context, and
          briefing workflows into one tactical intelligence surface.
        </p>
        <nav
          aria-label="Landing entry points"
          style={{
            display: "flex",
            flexWrap: "wrap",
            gap: "0.75rem",
            marginTop: "1.5rem",
          }}
        >
          {INTRO_ACTIONS.map((action, index) => (
            <Link
              key={action.to}
              to={action.to}
              className="mono"
              style={{
                border: `1px solid ${index === 0 ? "var(--amber)" : "var(--granite)"}`,
                color: index === 0 ? "var(--parchment)" : "var(--stone)",
                textDecoration: "none",
                textTransform: "uppercase",
                letterSpacing: "0.12em",
                fontSize: "0.72rem",
                padding: "0.75rem 0.95rem",
                background: index === 0 ? "rgba(196, 129, 58, 0.08)" : "transparent",
              }}
            >
              {action.label}
            </Link>
          ))}
        </nav>
      </div>

      <aside
        aria-label="ODIN capabilities"
        style={{
          border: "1px solid var(--granite)",
          padding: "1rem",
          display: "grid",
          gap: "0.75rem",
          alignContent: "start",
        }}
      >
        <SectionHeading label="Subsystemata" />
        {CAPABILITIES.map((capability) => (
          <div
            key={capability.label}
            style={{
              borderTop: "1px solid var(--granite)",
              paddingTop: "0.75rem",
            }}
          >
            <span className="mono" style={{ color: "var(--parchment)", fontSize: "0.78rem" }}>
              {capability.label}
            </span>
            <span
              style={{
                display: "block",
                marginTop: "0.2rem",
                color: "var(--stone)",
                fontSize: "0.84rem",
              }}
            >
              {capability.detail}
            </span>
          </div>
        ))}
      </aside>
    </section>
  );
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
        minHeight: 0,
        overflow: "auto",
      }}
    >
      <LandingIntro />

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
          gridTemplateColumns: "repeat(auto-fit, minmax(10rem, 1fr))",
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
          gridTemplateColumns: "repeat(auto-fit, minmax(min(100%, 18rem), 1fr))",
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
