import type { FlightDensity } from "./flightDensity";

export interface FlightStatus {
  density: FlightDensity | null;
  loading: boolean;
  error: string | null;
  lastUpdate: Date | null;
}

export function FlightSourceStatus({ density, loading, error, lastUpdate }: FlightStatus) {
  return <div role="status" aria-label="Flight source and rendering" style={{ fontSize: ".62rem", color: "var(--ash)" }}>
    {loading && <div>Kontakte laden…</div>}
    {error && <div style={{ color: "var(--amber)" }}>Abruf fehlgeschlagen · {lastUpdate ? "Vorheriger Clientstand" : "Nicht verfügbar"}</div>}
    {lastUpdate && density && <>
      {density.total === 0 ? <div>Keine Kontakte im letzten Clientabruf</div> : <>
        <div>{density.shown}/{density.inView} im Ausschnitt · {density.omitted} durch Darstellungslimit ausgeblendet</div>
        <div>{density.valid - density.inView} außerhalb · {density.invalid} ungültig · {density.duplicates} doppelt</div>
      </>}
    </>}
    {lastUpdate && <div>Clientabruf UTC: {lastUpdate.toISOString()}</div>}
    <div>Keine globale Vollständigkeit · Darstellung folgt Kameraabstand</div>
  </div>;
}
