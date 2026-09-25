import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { ReferenceGlobe } from "../components/landing/ReferenceGlobe";
import { FeedConnection } from "../components/hlidskjalf/FeedConnection";
import { NumericHero } from "../components/hlidskjalf/NumericHero";
import type { NumericAccent } from "../components/hlidskjalf/NumericHero";
import { useSignalFeed } from "../hooks/useSignalFeed";
import { getLandingSummary } from "../services/api";
import type { LandingSummary } from "../types/landing";
import type { SignalEnvelope } from "../types/signals";

const WORKFLOWS = [
  {
    n: "01",
    to: "/worldview?mode=overview",
    title: "Read the world",
    detail: "Place events in their geographic context.",
    tag: "SITUATION",
  },
  {
    n: "02",
    to: "/worldview?mode=infrastructure",
    title: "Follow the connections",
    detail: "Explore energy, transport and digital lifelines.",
    tag: "INFRASTRUCTURE",
  },
  {
    n: "03",
    to: "/briefing",
    title: "Build your understanding",
    detail: "Investigate the evidence. Bring it into a briefing.",
    tag: "INTELLIGENCE",
  },
] as const;

function utcDate(iso: string): string {
  const date = new Date(iso);
  if (!Number.isFinite(date.getTime())) return "Time unavailable";
  return (
    new Intl.DateTimeFormat("en-GB", {
      day: "2-digit",
      month: "short",
      year: "numeric",
      hour: "2-digit",
      minute: "2-digit",
      timeZone: "UTC",
    }).format(date) + " UTC"
  );
}

export function LandingPage() {
  const navigate = useNavigate();
  const [summary, setSummary] = useState<LandingSummary | null>(null);
  const [summaryError, setSummaryError] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const { items: feedItems, status } = useSignalFeed();

  useEffect(() => {
    let active = true;
    setSummaryError(false);
    void getLandingSummary("24h")
      .then((data) => {
        if (active) setSummary(data);
      })
      .catch(() => {
        if (active) setSummaryError(true);
      });
    return () => {
      active = false;
    };
  }, [attempt]);

  const tiles: {
    key: string;
    label: string;
    value: number | null;
    accent: NumericAccent;
    source?: string;
    to: string;
    pending?: boolean;
  }[] = [
    {
      key: "hotspots",
      label: "Hotspots",
      value: summary?.hotspots_24h ?? null,
      accent: "sent",
      source: summary?.hotspots_source,
      to: "/worldview?filter=hotspots",
    },
    {
      key: "conflict",
      label: "Conflict events",
      value: summary?.conflict_24h ?? null,
      accent: "amber",
      source: summary?.conflict_source,
      to: "/worldview?filter=conflict",
    },
    {
      key: "nuntii",
      label: "News signals",
      value: summary?.nuntii_24h ?? null,
      accent: "sage",
      source: summary?.nuntii_source,
      to: "/worldview?filter=nuntii",
    },
    {
      key: "libri",
      label: "Briefings",
      value: summary?.reports_not_available_yet
        ? null
        : (summary?.libri_24h ?? null),
      accent: "parchment",
      to: "/briefing",
      pending: summary?.reports_not_available_yet,
    },
  ];

  function openSignal(signal: SignalEnvelope) {
    const source =
      signal.payload.source || signal.type.replace(/^signal\./, "");
    const params = new URLSearchParams({
      entity: source + ":" + (signal.payload.redis_id || signal.event_id),
    });
    if (signal.payload.title) params.set("q", signal.payload.title);
    navigate("/worldview?" + params);
  }

  return (
    <div data-page="landing" className="situation-home">
      <div className="situation-masthead">
        <span className="eyebrow">ODIN · Hlíðskjalf</span>
        <span className="mono">GEOPOLITICAL OBSERVATORY</span>
      </div>
      <section data-part="landing-intro" className="situation-hero">
        <div className="situation-hero-copy">
          <span className="situation-edition">
            <span /> A WORLD IN CONTEXT
          </span>
          <h1>
            Your operating picture.
            <br />
            <em>A world connected.</em>
          </h1>
          <p>
            Go beyond the headline. Explore the places, movements and
            infrastructure shaping the geopolitical landscape.
          </p>
          <nav aria-label="Landing entry points" className="situation-actions">
            <Link
              className="observatory-button observatory-button-primary"
              to="/worldview?mode=overview"
            >
              Enter Worldview <span aria-hidden="true">↗</span>
            </Link>
            <Link className="observatory-button" to="/briefing">
              Open Briefing
            </Link>
            <Link className="situation-warroom" to="/warroom">
              War Room <span aria-hidden="true">↗</span>
            </Link>
          </nav>
          <div className="situation-hero-note">
            <span className="mono">01 — OBSERVE</span>
            <span>Locate. Connect. Understand.</span>
          </div>
        </div>
        <div className="situation-atlas">
          <div className="atlas-corner atlas-corner-tl" />
          <div className="atlas-corner atlas-corner-br" />
          <span className="atlas-heading mono">THE GLOBAL PERSPECTIVE</span>
          <ReferenceGlobe />
          <div className="atlas-caption">
            <span className="mono">GEOGRAPHIC REFERENCE</span>
            <span>
              Explore the interactive globe <span aria-hidden="true">↗</span>
            </span>
          </div>
          <Link
            className="atlas-link"
            to="/worldview?mode=overview"
            aria-label="Explore the interactive globe"
          />
        </div>
      </section>

      <section aria-label="Situation summary" className="situation-summary">
        <header className="situation-section-heading">
          <h2>
            At a glance <span>Last 24 hours</span>
          </h2>
          <div className="summary-status" role="status">
            {summaryError ? (
              <>
                <span>Summary unavailable</span>
                <button type="button" onClick={() => setAttempt((n) => n + 1)}>
                  Retry summary
                </button>
              </>
            ) : summary ? (
              <span>Snapshot · {utcDate(summary.generated_at)}</span>
            ) : (
              <span>Loading summary…</span>
            )}
          </div>
        </header>
        <div data-part="numerals" className="situation-metrics">
          {tiles.map((tile) => (
            <button
              className="situation-metric"
              key={tile.key}
              type="button"
              data-tile={tile.key}
              aria-label={tile.label}
              onClick={() => navigate(tile.to)}
            >
              <NumericHero
                value={tile.value ?? "—"}
                label={tile.label}
                accent={tile.accent}
                sub={
                  tile.pending
                    ? "Reports pending"
                    : tile.value === null
                      ? "Data unavailable"
                      : undefined
                }
              />
              <span className="metric-arrow" aria-hidden="true">
                ↗
              </span>
              {tile.source && (
                <span className="metric-source">Source · {tile.source}</span>
              )}
            </button>
          ))}
        </div>
      </section>

      <section className="situation-lower">
        <div className="situation-signals">
          <header className="situation-section-heading">
            <h2>Signal desk</h2>
            <FeedConnection status={status} />
          </header>
          <p className="situation-section-description">
            Latest received signals. Select a headline to investigate.
          </p>
          <div data-part="signal-feed">
            {feedItems.length === 0 ? (
              <div className="situation-empty">
                <span className="serif">Waiting for the next signal.</span>
                <p>
                  {status === "live"
                    ? "The stream is connected. Incoming signals will appear here."
                    : "The feed is not connected yet. You can still explore the map and your briefings."}
                </p>
                <Link to="/worldview?mode=overview">
                  Explore Worldview <span aria-hidden="true">↗</span>
                </Link>
              </div>
            ) : (
              feedItems.map((signal) => (
                <button
                  className="situation-signal"
                  type="button"
                  key={signal.event_id}
                  onClick={() => openSignal(signal)}
                >
                  <span
                    className="signal-severity"
                    data-severity={signal.payload.severity ?? "unknown"}
                    aria-hidden="true"
                  />
                  <span className="signal-story">
                    <span className="signal-meta">
                      {signal.payload.source ||
                        signal.type.replace(/^signal\./, "")}{" "}
                      <span>· {signal.payload.severity ?? "Unrated"}</span>
                    </span>
                    <span className="signal-headline">
                      {signal.payload.title || signal.type}
                    </span>
                    <time dateTime={signal.ts}>{utcDate(signal.ts)}</time>
                  </span>
                  <span className="signal-arrow" aria-hidden="true">
                    ↗
                  </span>
                </button>
              ))
            )}
          </div>
        </div>
        <aside
          className="situation-workflows"
          aria-label="Exploration workflows"
        >
          <header className="situation-section-heading">
            <h2>Choose your perspective</h2>
          </header>
          {WORKFLOWS.map((workflow) => (
            <Link
              key={workflow.n}
              to={workflow.to}
              className="situation-workflow"
            >
              <span className="workflow-number mono">{workflow.n}</span>
              <span>
                <span className="eyebrow">{workflow.tag}</span>
                <strong>{workflow.title}</strong>
                <span className="workflow-detail">{workflow.detail}</span>
              </span>
              <span aria-hidden="true">↗</span>
            </Link>
          ))}
        </aside>
      </section>
      <footer className="situation-footer">
        <span>ODIN / OPEN-SOURCE INTELLIGENCE</span>
        <span>Observe with curiosity. Assess with evidence.</span>
      </footer>
    </div>
  );
}
