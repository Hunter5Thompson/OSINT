import { useEffect, useMemo, useState, type CSSProperties } from "react";
import { NavLink } from "react-router-dom";
import { Orrery } from "./Orrery";

/**
 * Persistent top navigation bar (ODIN S1 · Task 7).
 *
 * Layout, per spec §3:
 *   ┌────────────────────────────────────────────────────────────────────┐
 *   │ ⊙ Hlíðskjalf    HOME  WORLDVIEW  BRIEFING  WAR ROOM    14·APR·26 / 16:42Z · UTC+02 │
 *   └────────────────────────────────────────────────────────────────────┘
 *
 * Behaviour notes:
 *  - Active tab: Parchment label + 5px Amber dot prefix.
 *  - War Room (inactive route): static 5px Sentinel dot — "watchful" without
 *    implying a live incident. Full pulse behaviour lands in Sprint 4.
 *  - Timestamp: UTC, shape `DD·MMM·YY / HH:MMZ`, re-computed every 30s.
 *  - Coarse location: UTC offset derived from `Date#getTimezoneOffset()`,
 *    falls back to the literal string `LOCAL` on failure.
 *  - Timestamp region is `aria-live="polite"`.
 *  - No CSS animation on any dot — Orrery component handles reduced-motion
 *    internally; the rest of the bar is static.
 */

const MONTHS = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"];

function pad2(n: number): string {
  return n < 10 ? `0${n}` : String(n);
}

/** Format a Date as `DD·MMM·YY / HH:MMZ` in UTC. */
export function formatUtcStamp(d: Date): string {
  const dd = pad2(d.getUTCDate());
  const mmm = MONTHS[d.getUTCMonth()];
  const yy = pad2(d.getUTCFullYear() % 100);
  const hh = pad2(d.getUTCHours());
  const mi = pad2(d.getUTCMinutes());
  return `${dd}·${mmm}·${yy} / ${hh}:${mi}Z`;
}

/**
 * Compute a coarse UTC offset string like `UTC+02`, `UTC-05`, `UTC+00`.
 * Returns the literal `LOCAL` if the offset cannot be resolved.
 *
 * Note: `Date#getTimezoneOffset()` returns minutes WEST of UTC, so we invert.
 */
export function coarseLocation(d: Date = new Date()): string {
  try {
    const offsetMin = -d.getTimezoneOffset();
    if (!Number.isFinite(offsetMin)) return "LOCAL";
    const sign = offsetMin >= 0 ? "+" : "-";
    const hours = Math.floor(Math.abs(offsetMin) / 60);
    return `UTC${sign}${pad2(hours)}`;
  } catch {
    return "LOCAL";
  }
}

const headerStyle: CSSProperties = {
  display: "flex",
  alignItems: "center",
  gap: "1.5rem",
  height: "48px",
  padding: "0 1.25rem",
  borderBottom: "1px solid var(--granite)",
  background: "transparent",
  color: "var(--ash)",
};

const brandStyle: CSSProperties = {
  display: "flex",
  alignItems: "center",
  gap: "0.5rem",
  color: "var(--parchment)",
};

const wordmarkStyle: CSSProperties = {
  fontFamily: '"Instrument Serif", "Times New Roman", serif',
  fontStyle: "italic",
  fontSize: "14px",
  letterSpacing: "0.02em",
};

const navStyle: CSSProperties = {
  display: "flex",
  alignItems: "center",
  gap: "1.25rem",
  flex: 1,
  justifyContent: "center",
};

const tabBaseStyle: CSSProperties = {
  display: "inline-flex",
  alignItems: "center",
  gap: "0.35rem",
  fontFamily: '"Hanken Grotesk", system-ui, sans-serif',
  fontSize: "10px",
  letterSpacing: "0.22em",
  textTransform: "uppercase",
  textDecoration: "none",
  color: "var(--ash)",
};

const tabActiveStyle: CSSProperties = {
  ...tabBaseStyle,
  color: "var(--parchment)",
};

const dotBase: CSSProperties = {
  display: "inline-block",
  width: "5px",
  height: "5px",
  borderRadius: "50%",
};

const activeDotStyle: CSSProperties = {
  ...dotBase,
  background: "var(--amber)",
};

const sentinelDotStyle: CSSProperties = {
  ...dotBase,
  background: "var(--sentinel)",
  opacity: 0.65,
};

const clockStyle: CSSProperties = {
  fontFamily: '"Martian Mono", ui-monospace, "SFMono-Regular", Consolas, monospace',
  fontSize: "10px",
  color: "var(--ash)",
  letterSpacing: "0.04em",
  whiteSpace: "nowrap",
};

interface TabDef {
  to: string;
  label: string;
}

const TABS: readonly TabDef[] = [
  { to: "/", label: "HOME" },
  { to: "/worldview", label: "WORLDVIEW" },
  { to: "/briefing", label: "BRIEFING" },
  { to: "/warroom", label: "WAR ROOM" },
] as const;

export function TopBar({ warRoomActive = false }: { warRoomActive?: boolean }) {
  const [now, setNow] = useState<Date>(() => new Date());

  useEffect(() => {
    const id = window.setInterval(() => {
      setNow(new Date());
    }, 30_000);
    return () => window.clearInterval(id);
  }, []);

  const stamp = useMemo(() => formatUtcStamp(now), [now]);
  // Location is computed once per mount — the host timezone does not change
  // during a session in any realistic scenario.
  const location = useMemo(() => coarseLocation(), []);

  return (
    <header style={headerStyle} role="banner">
      <div style={brandStyle}>
        <Orrery size="s" />
        <span style={wordmarkStyle}>Hlíðskjalf</span>
      </div>

      <nav style={navStyle} aria-label="Primary">
        {TABS.map((tab) => (
          <NavLink
            key={tab.to}
            to={tab.to}
            end={tab.to === "/"}
            style={({ isActive }) => (isActive ? tabActiveStyle : tabBaseStyle)}
          >
            {({ isActive }) => {
              const isWarRoom = tab.to === "/warroom";
              return (
                <>
                  {isActive ? (
                    <span data-tab-dot="active" style={activeDotStyle} aria-hidden="true" />
                  ) : isWarRoom ? (
                    <span
                      data-tab-dot={warRoomActive ? "pulsing" : "sentinel"}
                      className={warRoomActive ? "hlid-pulse" : undefined}
                      style={{
                        ...sentinelDotStyle,
                        opacity: warRoomActive ? 1 : 0.65,
                      }}
                      aria-hidden="true"
                    />
                  ) : null}
                  <span>{tab.label}</span>
                </>
              );
            }}
          </NavLink>
        ))}
      </nav>

      <div
        data-testid="topbar-clock"
        style={clockStyle}
        aria-live="polite"
        aria-label="Current UTC time and local offset"
      >
        {stamp} · {location}
      </div>
    </header>
  );
}
