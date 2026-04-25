import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";

import { IncidentBar } from "../components/hlidskjalf/IncidentBar";
import { TheatreQuadrant } from "../components/warroom/TheatreQuadrant";
import { TimelineQuadrant } from "../components/warroom/TimelineQuadrant";
import {
  MuninStreamQuadrant,
  type MuninToolCall,
} from "../components/warroom/MuninStreamQuadrant";
import { RawSourcesQuadrant } from "../components/warroom/RawSourcesQuadrant";
import { useIncidents } from "../hooks/useIncidents";
import {
  getConfig,
  getIncident,
  promoteIncident,
  queryIntel,
  silenceIncident,
} from "../services/api";
import type { Incident } from "../types/incident";

import "../components/warroom/warRoomLayout.css";

export function WarRoomPage() {
  const params = useParams<{ incidentId?: string }>();
  const navigate = useNavigate();
  const { active } = useIncidents();
  const [routedIncident, setRoutedIncident] = useState<Incident | null>(null);
  const [token, setToken] = useState<string>("");
  const [toolCalls, setToolCalls] = useState<MuninToolCall[]>([]);
  const [hypothesis, setHypothesis] = useState<string>("");
  const [busy, setBusy] = useState<boolean>(false);
  const abortRef = useRef<AbortController | null>(null);

  // Resolve which incident this page should display.
  useEffect(() => {
    let cancelled = false;
    if (!params.incidentId) {
      setRoutedIncident(null);
      return;
    }
    void getIncident(params.incidentId)
      .then((rec) => {
        if (!cancelled) setRoutedIncident(rec);
      })
      .catch(() => {
        if (!cancelled) setRoutedIncident(null);
      });
    return () => {
      cancelled = true;
    };
  }, [params.incidentId]);

  const incident = routedIncident ?? active;

  // Cesium token (one-shot fetch; component-level cache is fine for v1).
  useEffect(() => {
    void getConfig()
      .then((cfg) => setToken(cfg.cesium_ion_token ?? ""))
      .catch(() => setToken(""));
  }, []);

  // Reset Munin surface when the incident changes; abort any in-flight query.
  useEffect(() => {
    abortRef.current?.abort();
    abortRef.current = null;
    setToolCalls([]);
    setHypothesis("");
    setBusy(false);
  }, [incident?.id]);

  const handlePromote = useCallback(async () => {
    if (!incident) return;
    await promoteIncident(incident.id);
    navigate(`/briefing?from=incident&id=${encodeURIComponent(incident.id)}`);
  }, [incident, navigate]);

  const handleSilence = useCallback(async () => {
    if (!incident) return;
    await silenceIncident(incident.id);
  }, [incident]);

  const handleAsk = useCallback(
    (prompt: string) => {
      if (!incident || busy) return;
      setToolCalls((prev) => [
        ...prev,
        {
          tplus: nowTplus(incident),
          tool: "munin.ask",
          detail: prompt.slice(0, 80),
          tone: "amber",
        },
      ]);
      setHypothesis(`Pending: «${prompt}»`);
      setBusy(true);

      const region = `${incident.coords[0].toFixed(3)},${incident.coords[1].toFixed(3)}`;
      const controller = queryIntel(
        {
          query: `[incident ${incident.id} · ${incident.title}] ${prompt}`,
          region,
        },
        (status) => {
          setToolCalls((prev) => [
            ...prev,
            {
              tplus: nowTplus(incident),
              tool: status.agent || "agent",
              detail: status.status ?? "running",
              tone: "sage",
            },
          ]);
        },
        (analysis) => {
          const body = analysis.analysis?.trim() ?? "";
          const label = analysis.threat_assessment?.trim() ?? "";
          const composed = label ? `[${label}] ${body}` : body;
          setHypothesis(composed || "Munin returned no synthesis.");
        },
        (error) => {
          setToolCalls((prev) => [
            ...prev,
            {
              tplus: nowTplus(incident),
              tool: "munin.error",
              detail: error.slice(0, 80),
              tone: "sentinel",
            },
          ]);
          setBusy(false);
          abortRef.current = null;
        },
        () => {
          setBusy(false);
          abortRef.current = null;
        },
      );
      abortRef.current = controller;
    },
    [incident, busy],
  );

  // Cancel any in-flight query on unmount.
  useEffect(() => {
    return () => {
      abortRef.current?.abort();
      abortRef.current = null;
    };
  }, []);

  const incidentBar = useMemo(
    () => (incident ? <IncidentBar incident={incident} /> : null),
    [incident],
  );

  return (
    <div style={{ display: "flex", flexDirection: "column", flex: 1, minHeight: 0 }} data-page="warroom">
      {incidentBar}
      <div className="warroom-grid">
        <div className="warroom-cell">
          <TheatreQuadrant incident={incident} cesiumToken={token} />
        </div>
        <div className="warroom-cell">
          {incident ? (
            <TimelineQuadrant incident={incident} />
          ) : (
            <div className="warroom-empty">§ Timeline · empty</div>
          )}
        </div>
        <div className="warroom-cell">
          <MuninStreamQuadrant
            toolCalls={toolCalls}
            hypothesis={hypothesis}
            onAsk={handleAsk}
            busy={busy}
          />
        </div>
        <div className="warroom-cell">
          {incident ? (
            <RawSourcesQuadrant
              incident={incident}
              onPromote={handlePromote}
              onSilence={handleSilence}
              onAsk={() => handleAsk("Brief me on this incident")}
            />
          ) : (
            <div className="warroom-empty">§ Raw · sources · none</div>
          )}
        </div>
      </div>
    </div>
  );
}

function nowTplus(incident: Incident | null): string {
  if (!incident) return "T+00:00:00";
  const seconds = Math.max(
    0,
    Math.floor((Date.now() - Date.parse(incident.trigger_ts)) / 1000),
  );
  const hh = String(Math.floor(seconds / 3600)).padStart(2, "0");
  const mm = String(Math.floor((seconds % 3600) / 60)).padStart(2, "0");
  const ss = String(seconds % 60).padStart(2, "0");
  return `T+${hh}:${mm}:${ss}`;
}
