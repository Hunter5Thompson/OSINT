import type { ResearchCoverage } from "../../types";

const labels: Record<ResearchCoverage["status"], string> = {
  complete: "Abrufe abgeschlossen", partial: "eingeschränkt",
  unavailable: "nicht verfügbar", not_requested: "nicht angefordert",
};
const gaps: Record<string, string> = {
  local_corpus_unavailable: "Der lokale Quellenkorpus war nicht erreichbar.",
  original_unavailable: "Mindestens ein Originaltext konnte nicht gelesen werden.",
  not_configured: "Die Webrecherche ist nicht eingerichtet.",
  rate_limited: "Der Suchanbieter begrenzt weitere Abrufe.",
  authentication_failed: "Die Anmeldung beim Suchanbieter ist fehlgeschlagen.",
  budget_exhausted: "Das Abrufbudget dieses Berichts ist ausgeschöpft.",
  deadline_exceeded: "Das Recherchezeitfenster ist abgelaufen.",
  timeout: "Ein Abruf hat sein Zeitlimit überschritten.",
  invalid_results: "Nicht verwendbare Suchtreffer wurden verworfen.",
  prompt_budget: "Der Berichtskontext begrenzt die verwendbaren Belege.",
};

export function CurrentResearchCoverage({ coverage }: { coverage?: ResearchCoverage | null }) {
  if (!coverage) return null;
  return <section aria-label="Aktuelle Recherche" data-testid="current-research-coverage"
    style={{ fontSize: ".8rem", lineHeight: 1.6, margin: "12px 0" }}>
    <strong>Aktuelle Recherche · {labels[coverage.status]}</strong>
    <p>Stand: {coverage.as_of} · Publikationsfenster ab {coverage.published_since}</p>
    <p>{coverage.situation === "evidence_available"
      ? `${coverage.current_evidence_ids.length} datierte Originalbelege im Berichtskontext; Aussagen ungeprüft.`
      : coverage.situation === "research_failed" ? "Aktuelle Recherche technisch nicht verfügbar."
        : "Keine ausreichenden aktuellen Originalbelege."}<br />
      Prognose: {coverage.forecast === "not_requested" ? "nicht angefordert" : "nicht belastbar bewertet"}.
      Mögliche Szenarien sind bedingte Überlegungen.</p>
    {coverage.gaps.length > 0 && <ul>{coverage.gaps.map(code =>
      <li key={code}>{gaps[code] ?? "Eine Recherchequelle war nicht verfügbar."}</li>)}</ul>}
  </section>;
}
