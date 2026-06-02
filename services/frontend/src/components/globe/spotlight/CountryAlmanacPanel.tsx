import { useEffect, useMemo, useState } from "react";

import { useCountryAlmanac } from "../../../hooks/useCountryAlmanac";
import { useCountryBriefing } from "../../../hooks/useCountryBriefing";
import { saveCountryBriefing } from "../../../services/api";
import type { AlmanacFact, AlmanacFacts, AlmanacSignalItem } from "../../../types/almanac";

const sections: Array<{ key: keyof AlmanacFacts; label: string }> = [
  { key: "profile", label: "Profile" },
  { key: "people", label: "People" },
  { key: "government", label: "Gov" },
  { key: "economy", label: "Economy" },
  { key: "security", label: "Security" },
];

const capabilities = ["Hugin", "Signalia", "Vectorium", "Memoria", "Fenestra"];

interface Props {
  iso3: string | null;
  m49: string;
}

export function CountryAlmanacPanel({ iso3, m49 }: Props) {
  const { facts, signals } = useCountryAlmanac({ iso3, m49 });
  const [active, setActive] = useState<keyof AlmanacFacts>("profile");

  const countryId = iso3 ?? m49;
  const briefing = useCountryBriefing(countryId);
  const [saved, setSaved] = useState(false);
  const [savedId, setSavedId] = useState<string | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);

  useEffect(() => {
    // inspected country changed → drop any prior briefing result + save state so we never
    // show or save country A's briefing under country B.
    setSaved(false);
    setSavedId(null);
    setSaveError(null);
    briefing.reset();
  }, [countryId]);

  const activeFacts = useMemo<AlmanacFact[]>(() => {
    if (facts.status !== "ready") return [];
    return facts.data.facts[active] ?? [];
  }, [active, facts]);

  return (
    <section className="country-almanac" aria-label="WorldReport Almanac">
      <div className="country-almanac__eyebrow">§ Almanac · WorldReport</div>
      {facts.status === "loading" && (
        <div className="country-almanac__muted">§ Almanac · loading</div>
      )}
      {facts.status === "error" && (
        <div className="country-almanac__muted">§ Almanac · unavailable for this country</div>
      )}
      {facts.status === "ready" && (
        <>
          <div className="country-almanac__meta">
            {[facts.data.region, facts.data.subregion].filter(Boolean).join(" · ")}
          </div>
          <div className="country-almanac__tabs" aria-label="Almanac sections">
            {sections.map((section) => (
              <button
                key={section.key}
                type="button"
                className={
                  section.key === active
                    ? "country-almanac__tab is-active"
                    : "country-almanac__tab"
                }
                onClick={() => setActive(section.key)}
              >
                {section.label}
              </button>
            ))}
          </div>
          <dl className="country-almanac__facts">
            {activeFacts.length > 0 ? (
              activeFacts.map((fact) => (
                <div className="country-almanac__fact" key={`${fact.label}:${fact.value}`}>
                  <dt>{fact.label}</dt>
                  <dd>{fact.value}</dd>
                </div>
              ))
            ) : (
              <div className="country-almanac__muted">No facts in this section yet</div>
            )}
          </dl>
        </>
      )}
      <SignalList status={signals.status} items={signals.status === "ready" ? signals.data.items : []} />
      <section className="country-almanac__briefing" aria-label="Munin briefing">
        <button
          type="button"
          className="country-almanac__tab"
          onClick={() => {
            setSaved(false);
            setSavedId(null);
            setSaveError(null);
            briefing.run();
          }}
        >
          § Munin-Briefing erzeugen
        </button>
        {briefing.loading && (
          <div className="country-almanac__muted">§ Munin · {briefing.currentAgent ?? "läuft"}</div>
        )}
        {briefing.error && <div className="country-almanac__muted">§ Munin · {briefing.error}</div>}
        {briefing.result && (
          <details className="country-almanac__report">
            <summary>
              {briefing.result.threat_assessment ?? "REPORT"} ·{" "}
              {(briefing.result.confidence * 100).toFixed(0)}%
            </summary>
            <pre className="country-almanac__report-body">{briefing.result.analysis}</pre>
            <button
              type="button"
              className="country-almanac__tab"
              disabled={saved}
              onClick={() => {
                const r = briefing.result;
                if (!r) return;
                setSaveError(null);
                saveCountryBriefing(countryId, r)
                  .then((rec) => {
                    setSaved(true);
                    setSavedId(rec.id);
                  })
                  .catch((e: unknown) => setSaveError(e instanceof Error ? e.message : String(e)));
              }}
            >
              {saved ? "✓ in Briefing Room" : "In Briefing Room speichern"}
            </button>
            {savedId && (
              <a className="country-almanac__tab" href={`/briefing/${savedId}`}>
                Im Briefing Room öffnen →
              </a>
            )}
            {saveError && <div className="country-almanac__muted">§ Speichern · {saveError}</div>}
          </details>
        )}
      </section>
      <div className="country-almanac__capabilities" aria-label="ODIN capabilities">
        {capabilities.map((capability) => (
          <span key={capability}>{capability}</span>
        ))}
      </div>
    </section>
  );
}

function SignalList({
  status,
  items,
}: {
  status: "idle" | "loading" | "ready" | "error";
  items: AlmanacSignalItem[];
}) {
  return (
    <section className="country-almanac__signals" aria-label="Active ODIN signals">
      <h4>Active ODIN Signals</h4>
      {status === "loading" && <div className="country-almanac__muted">§ Signals · loading</div>}
      {status === "error" && <div className="country-almanac__muted">§ Signals · unavailable</div>}
      {status === "ready" && items.length === 0 && (
        <div className="country-almanac__muted">No linked ODIN signals in current window</div>
      )}
      {status === "ready" &&
        items.map((item) => (
          <div className="country-almanac__signal" key={item.event_id}>
            {item.url ? (
              <a href={item.url} target="_blank" rel="noreferrer">
                {item.title}
              </a>
            ) : (
              <b>{item.title}</b>
            )}
            <span>
              {item.severity} · {item.source || item.type}
            </span>
          </div>
        ))}
    </section>
  );
}
