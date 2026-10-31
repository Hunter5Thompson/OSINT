import type { OrbitSnapshot } from "../../types/satelliteOrbit";

interface Props {
  snapshot: OrbitSnapshot | null;
  loading: boolean;
  error: string | null;
}

export function SatelliteSourceStatus({ snapshot, loading, error }: Props) {
  const groups = snapshot?.coverage.groups ?? [];
  const usable = groups.filter(group => group.status !== "failed").length;
  const rejected = groups.reduce((sum, group) => sum + group.rejected_invalid + group.rejected_unsupported, 0);
  const stale = snapshot && Date.now() - Date.parse(snapshot.fetched_at) > 7_200_000;
  return (
    <div role="status" aria-live="polite" className="pointer-events-none absolute top-24 right-4 z-20 max-w-xs rounded border border-white/15 bg-black/80 p-2 text-xs text-white/75">
      <div>Satelliten{loading ? " · laden…" : ""}</div>
      {error && <div className="text-amber-300">Abruf fehlgeschlagen · {snapshot ? "Vorheriger Quellstand" : "Nicht verfügbar"}</div>}
      {snapshot && <>
        <div>{snapshot.satellites.length} Satelliten · {usable}/{groups.length} Gruppen{snapshot.coverage.completeness === "partial" ? " · Teilabdeckung" : ""}</div>
        <div>Quellabruf UTC: {snapshot.fetched_at}</div>
        {stale && <div className="text-amber-300">Veralteter Quellstand</div>}
        {(rejected > 0 || snapshot.client_rejections.length > 0) &&
          <div>{rejected} Quelldatensätze und {snapshot.client_rejections.length} Clientdatensätze verworfen</div>}
      </>}
    </div>
  );
}
