import { useEffect, useMemo, useRef, useState } from "react";

import { useCountryAlmanac } from "../../../hooks/useCountryAlmanac";
import { useCountryBriefing } from "../../../hooks/useCountryBriefing";
import { useSpatialCountryBriefing } from "../../../hooks/useSpatialCountryBriefing";
import type { SpatialCountryAlmanacState } from "../../../hooks/useSpatialCountryAlmanac";
import { useSpatialCountrySignals } from "../../../hooks/useSpatialCountrySignals";
import {
  saveCountryBriefing,
  saveSpatialCountryBriefing,
} from "../../../services/api";
import type { SpatialQueryRef } from "../../../spatial/contracts";
import type { IntelAnalysis } from "../../../types";
import type {
  AlmanacFact,
  AlmanacFacts,
  AlmanacSignalItem,
  CountryAlmanac,
} from "../../../types/almanac";

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

  const countryId = iso3 ?? m49;
  const briefing = useCountryBriefing(countryId);

  return (
    <section className="country-almanac" aria-label="WorldReport Almanac">
      <AlmanacFactsContent facts={facts} />
      <SignalList status={signals.status} items={signals.status === "ready" ? signals.data.items : []} />
      <CountryBriefingContent
        identity={`legacy:${countryId}`}
        briefing={briefing}
        save={(analysis) => saveCountryBriefing(countryId, analysis)}
      />
      <CapabilityList />
    </section>
  );
}

type AlmanacFactsLoadState =
  | { readonly status: "idle"; readonly data: null; readonly error: null }
  | { readonly status: "loading"; readonly data: null; readonly error: null }
  | { readonly status: "ready"; readonly data: CountryAlmanac; readonly error: null }
  | { readonly status: "error"; readonly data: null; readonly error: string };

export function SpatialCountryAlmanacPanel({
  facts,
  query,
}: {
  readonly facts: SpatialCountryAlmanacState;
  readonly query: SpatialQueryRef | null;
}) {
  const signals = useSpatialCountrySignals(query);
  const briefing = useSpatialCountryBriefing(query);
  const identity = query === null
    ? "spatial:none"
    : `spatial:${query.scopeKey}\u0000${query.catalogRevision}`;

  return (
    <section className="country-almanac" aria-label="WorldReport Almanac">
      <AlmanacFactsContent facts={facts} />
      <SignalList
        status={signals.status}
        items={signals.status === "ready" ? signals.data.items : []}
      />
      <CountryBriefingContent
        identity={identity}
        briefing={briefing}
        save={query === null
          ? null
          : (analysis, signal) => saveSpatialCountryBriefing(query, analysis, signal)}
      />
      <CapabilityList />
    </section>
  );
}

type BriefingController = ReturnType<typeof useCountryBriefing>;
type SaveBriefing = (
  analysis: IntelAnalysis,
  signal: AbortSignal,
) => Promise<{ readonly id: string }>;

function CountryBriefingContent({
  identity,
  briefing,
  save,
}: {
  readonly identity: string;
  readonly briefing: BriefingController;
  readonly save: SaveBriefing | null;
}) {
  const [saved, setSaved] = useState(false);
  const [savedId, setSavedId] = useState<string | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);
  const saveControllerRef = useRef<AbortController | null>(null);
  const activeIdentityRef = useRef(identity);
  activeIdentityRef.current = identity;

  useEffect(() => {
    saveControllerRef.current?.abort();
    saveControllerRef.current = null;
    setSaved(false);
    setSavedId(null);
    setSaveError(null);
    briefing.reset();
    return () => saveControllerRef.current?.abort();
  }, [briefing.reset, identity]);

  return (
    <section className="country-almanac__briefing" aria-label="Munin briefing">
      <button
        type="button"
        className="country-almanac__tab"
        onClick={() => {
          saveControllerRef.current?.abort();
          setSaved(false);
          setSavedId(null);
          setSaveError(null);
          briefing.run();
        }}
      >
        § Munin-Briefing erzeugen
      </button>
      {briefing.loading && (
        <div className="country-almanac__muted">
          § Munin · {briefing.currentAgent ?? "läuft"}
        </div>
      )}
      {briefing.error && (
        <div className="country-almanac__muted">§ Munin · {briefing.error}</div>
      )}
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
            disabled={saved || save === null}
            onClick={() => {
              const result = briefing.result;
              if (result === null || save === null) return;
              saveControllerRef.current?.abort();
              const controller = new AbortController();
              const requestedIdentity = identity;
              saveControllerRef.current = controller;
              setSaveError(null);
              save(result, controller.signal)
                .then((record) => {
                  if (
                    !controller.signal.aborted
                    && activeIdentityRef.current === requestedIdentity
                  ) {
                    setSaved(true);
                    setSavedId(record.id);
                  }
                })
                .catch((error: unknown) => {
                  if (
                    !controller.signal.aborted
                    && activeIdentityRef.current === requestedIdentity
                  ) {
                    setSaveError(error instanceof Error ? error.message : String(error));
                  }
                });
            }}
          >
            {saved ? "✓ in Briefing Room" : "In Briefing Room speichern"}
          </button>
          {savedId && (
            <a className="country-almanac__tab" href={`/briefing/${savedId}`}>
              Im Briefing Room öffnen →
            </a>
          )}
          {saveError && (
            <div className="country-almanac__muted">§ Speichern · {saveError}</div>
          )}
        </details>
      )}
    </section>
  );
}

function CapabilityList() {
  return (
    <div className="country-almanac__capabilities" aria-label="ODIN capabilities">
      {capabilities.map((capability) => (
        <span key={capability}>{capability}</span>
      ))}
    </div>
  );
}

function AlmanacFactsContent({ facts }: { readonly facts: AlmanacFactsLoadState }) {
  const [active, setActive] = useState<keyof AlmanacFacts>("profile");
  const activeFacts = useMemo<AlmanacFact[]>(() => {
    if (facts.status !== "ready") return [];
    return facts.data.facts[active] ?? [];
  }, [active, facts]);

  return (
    <>
      <div className="country-almanac__eyebrow">§ Almanac · WorldReport</div>
      {facts.status === "idle" && (
        <div className="country-almanac__muted">§ Almanac · awaiting committed scope</div>
      )}
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
    </>
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
