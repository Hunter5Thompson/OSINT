import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { MuninLoader } from "../components/worldview/MuninLoader";
import { useIntel } from "../hooks/useIntel";
import {
  createReport,
  getReportMessages,
  getReports,
  updateReport,
} from "../services/api";
import type {
  DossierMetric,
  MessageRole,
  ReportMessage,
  ReportRecord,
} from "../types";
import "./briefingPage.css";

type AccentTone = DossierMetric["tone"];

function toneClass(tone: AccentTone): string {
  if (tone === "amber") return "briefing-tone-amber";
  if (tone === "sage") return "briefing-tone-sage";
  return "briefing-tone-sentinel";
}

function statusToken(status: ReportRecord["status"]): string {
  if (status === "Published") return "published";
  if (status === "Archived") return "archived";
  return "draft";
}

function confidence(conf: number): string {
  return conf.toFixed(2);
}

function displayTs(ts: string): string {
  const d = new Date(ts);
  if (Number.isNaN(d.getTime())) return ts;
  const hh = String(d.getUTCHours()).padStart(2, "0");
  const mm = String(d.getUTCMinutes()).padStart(2, "0");
  return `${hh}:${mm}Z`;
}

function inferWorldviewLayer(report: ReportRecord): string {
  const blob = `${report.title} ${report.sources.join(" ")} ${report.context}`.toLowerCase();
  if (blob.includes("firms") || blob.includes("hotspot")) return "firmsHotspots";
  if (blob.includes("cable")) return "cables";
  if (blob.includes("pipeline")) return "pipelines";
  if (blob.includes("satellite")) return "satellites";
  if (blob.includes("aircraft") || blob.includes("flight")) return "milAircraft";
  if (blob.includes("datacenter")) return "datacenters";
  if (blob.includes("refiner")) return "refineries";
  return "events";
}

function normalizeError(err: unknown): string {
  if (err instanceof Error) return err.message;
  return String(err);
}

export function BriefingPage() {
  const navigate = useNavigate();

  const [reports, setReports] = useState<ReportRecord[]>([]);
  const [reportsLoading, setReportsLoading] = useState(true);
  const [reportsError, setReportsError] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<string>("");
  const [filter, setFilter] = useState("");
  const [expandedBody, setExpandedBody] = useState(false);

  const [chatByReport, setChatByReport] = useState<Record<string, ReportMessage[]>>({});
  const [chatLoading, setChatLoading] = useState(false);

  const [input, setInput] = useState("");
  const [muninDownUntil, setMuninDownUntil] = useState<number | null>(null);
  const [tick, setTick] = useState(0);

  const {
    loading: muninLoading,
    currentAgent,
    result,
    error,
    runQuery,
  } = useIntel();

  const abortRef = useRef<(() => void) | null>(null);
  const pendingReportIdRef = useRef<string | null>(null);
  const processedResultKey = useRef<string>("");
  const processedErrorKey = useRef<string>("");
  const wasLoadingRef = useRef(false);

  useEffect(() => {
    if (muninDownUntil === null) return;
    setTick(Date.now());
    const id = window.setInterval(() => setTick(Date.now()), 1000);
    return () => window.clearInterval(id);
  }, [muninDownUntil]);

  const retryIn = useMemo(() => {
    if (!muninDownUntil) return 0;
    const now = tick || Date.now();
    return Math.max(0, Math.ceil((muninDownUntil - now) / 1000));
  }, [muninDownUntil, tick]);

  const muninOffline = retryIn > 0;

  useEffect(() => {
    if (retryIn === 0 && muninDownUntil !== null) {
      setMuninDownUntil(null);
    }
  }, [retryIn, muninDownUntil]);

  const loadReports = useCallback(async () => {
    setReportsLoading(true);
    try {
      const rows = await getReports();
      setReports(rows);
      setReportsError(null);
      setSelectedId((prev) => {
        if (prev && rows.some((r) => r.id === prev)) return prev;
        return rows[0]?.id ?? "";
      });
    } catch (err) {
      setReportsError(normalizeError(err));
    } finally {
      setReportsLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadReports();
  }, [loadReports]);

  const selectedReport = useMemo(() => {
    const explicit = reports.find((r) => r.id === selectedId);
    if (explicit) return explicit;
    return reports[0] ?? null;
  }, [reports, selectedId]);

  useEffect(() => {
    if (!selectedReport) return;
    setSelectedId(selectedReport.id);
  }, [selectedReport]);

  const loadMessages = useCallback(async (reportId: string) => {
    setChatLoading(true);
    try {
      const messages = await getReportMessages(reportId);
      setChatByReport((prev) => ({ ...prev, [reportId]: messages }));
    } catch {
      // keep local in-memory view; backend errors are reflected by munin state when querying
    } finally {
      setChatLoading(false);
    }
  }, []);

  useEffect(() => {
    if (!selectedReport) return;
    setExpandedBody(false);
    setInput("");
    void loadMessages(selectedReport.id);
  }, [selectedReport?.id, loadMessages]);

  useEffect(() => {
    if (wasLoadingRef.current && !muninLoading) {
      const reportId = pendingReportIdRef.current;
      if (reportId) {
        void loadMessages(reportId);
      }
      pendingReportIdRef.current = null;
    }
    wasLoadingRef.current = muninLoading;
  }, [muninLoading, loadMessages]);

  const filtered = useMemo(() => {
    const q = filter.trim().toLowerCase();
    const sorted = [...reports].sort((a, b) => b.paragraph_num - a.paragraph_num);

    if (!q) return sorted;
    return sorted.filter((report) => {
      const blob = [
        report.title,
        report.status,
        report.location,
        report.coords,
        report.stamp,
        String(report.paragraph_num),
      ]
        .join(" ")
        .toLowerCase();
      return blob.includes(q);
    });
  }, [filter, reports]);

  const chatMessages = selectedReport ? (chatByReport[selectedReport.id] ?? []) : [];

  const appendChat = (reportId: string, message: ReportMessage) => {
    setChatByReport((prev) => ({
      ...prev,
      [reportId]: [...(prev[reportId] ?? []), message],
    }));
  };

  useEffect(() => {
    if (!result) return;
    const key = `${result.timestamp}|${result.analysis}`;
    if (processedResultKey.current === key) return;
    processedResultKey.current = key;

    const reportId = pendingReportIdRef.current ?? selectedReport?.id;
    if (!reportId) return;

    appendChat(reportId, {
      id: `m-${Date.now()}`,
      role: "munin",
      ts: new Date().toISOString(),
      text: result.analysis,
      refs: result.sources_used.slice(0, 6),
    });
  }, [result, selectedReport?.id]);

  useEffect(() => {
    if (!error) return;
    const key = `${error}|${selectedReport?.id ?? "none"}`;
    if (processedErrorKey.current === key) return;
    processedErrorKey.current = key;

    if (selectedReport) {
      appendChat(selectedReport.id, {
        id: `m-err-${Date.now()}`,
        role: "munin",
        ts: new Date().toISOString(),
        text: "service unreachable · retry in 10s",
        refs: [],
      });
    }

    setMuninDownUntil(Date.now() + 10_000);
  }, [error, selectedReport]);

  useEffect(() => {
    return () => {
      abortRef.current?.();
    };
  }, []);

  const createDossier = async () => {
    try {
      const created = await createReport({});
      setReports((prev) => [created, ...prev.filter((r) => r.id !== created.id)]);
      setSelectedId(created.id);
      setExpandedBody(false);
      setReportsError(null);
    } catch (err) {
      setReportsError(normalizeError(err));
    }
  };

  const promoteToWorldview = async (report: ReportRecord) => {
    const params = new URLSearchParams();
    params.set("layer", inferWorldviewLayer(report));
    if (report.location && !report.location.toLowerCase().includes("unspecified")) {
      params.set("entity", report.location);
    }

    if (report.status !== "Published") {
      try {
        const updated = await updateReport(report.id, { status: "Published" });
        setReports((prev) => prev.map((r) => (r.id === updated.id ? updated : r)));
      } catch {
        // non-blocking for navigation
      }
    }

    navigate(`/worldview?${params.toString()}`);
  };

  const askMunin = async (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    if (!selectedReport || muninOffline || muninLoading) return;

    const question = input.trim();
    if (!question) return;

    const localUserMessage: ReportMessage = {
      id: `u-${Date.now()}`,
      role: "user",
      ts: new Date().toISOString(),
      text: question,
      refs: [],
    };
    appendChat(selectedReport.id, localUserMessage);

    setInput("");
    pendingReportIdRef.current = selectedReport.id;
    abortRef.current?.();

    abortRef.current = runQuery({
      query: `Report ${selectedReport.paragraph_num} (${selectedReport.title}): ${question}`,
      report_id: selectedReport.id,
      report_message: question,
    });
  };

  return (
    <div className="briefing-page" data-page="briefing">
      <aside className="briefing-col briefing-index">
        <header className="briefing-index-header">
          <div>
            <div className="briefing-eyebrow mono">Section III</div>
            <h2 className="serif briefing-title">Dossier Archive</h2>
          </div>
          <button type="button" className="briefing-action" onClick={createDossier}>
            + New Dossier
          </button>
        </header>

        <label className="briefing-filter-wrap" htmlFor="briefing-filter">
          <span className="mono briefing-filter-label">▸ filter / search</span>
          <input
            id="briefing-filter"
            className="briefing-filter"
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            placeholder="date, entity, status"
          />
        </label>

        <div className="briefing-list custom-scrollbar">
          {reportsLoading ? (
            <div className="briefing-empty">
              <div className="mono">§ loading dossier archive...</div>
            </div>
          ) : filtered.length === 0 ? (
            <div className="briefing-empty">
              <div className="serif">
                § — · {reportsError ? "dossier archive unreachable" : "no dossiers yet"}
              </div>
              <button
                type="button"
                className="briefing-link"
                onClick={() => {
                  setFilter("");
                  void loadReports();
                }}
              >
                ▸ retry
              </button>
              {reportsError ? <div className="mono" style={{ marginTop: 8 }}>{reportsError}</div> : null}
            </div>
          ) : (
            filtered.map((report) => (
              <button
                key={report.id}
                type="button"
                className={`briefing-report-item ${selectedReport?.id === report.id ? "is-active" : ""}`}
                onClick={() => {
                  setSelectedId(report.id);
                  setExpandedBody(false);
                }}
              >
                <div className="mono briefing-report-meta">{`§ ${String(report.paragraph_num).padStart(3, "0")} · ${report.stamp}`}</div>
                <div className="serif briefing-report-title">{report.title}</div>
                <div className="mono briefing-report-sub">{`${statusToken(report.status)} · conf ${confidence(report.confidence)}`}</div>
              </button>
            ))
          )}
        </div>
      </aside>

      <section className="briefing-col briefing-dossier">
        {!selectedReport ? (
          <div className="briefing-empty-center serif">Create your first dossier.</div>
        ) : (
          <div className="briefing-dossier-scroll custom-scrollbar">
            <header className="briefing-dossier-header">
              <div className="briefing-dossier-headline mono">
                {`§ ${String(selectedReport.paragraph_num).padStart(3, "0")} · ${statusToken(selectedReport.status)} · conf ${confidence(selectedReport.confidence)}`}
              </div>
              <h1 className="serif briefing-dossier-title">{selectedReport.title}</h1>
              <div className="mono briefing-dossier-submeta">
                {`${selectedReport.stamp} · ${selectedReport.location} · ${selectedReport.coords}`}
              </div>
            </header>

            <hr className="hair" />

            <section>
              <div className="briefing-section-label mono">§ Findings</div>
              <ol className="briefing-findings">
                {selectedReport.findings.map((finding, idx) => (
                  <li key={`${selectedReport.id}-f-${idx}`}>
                    <span className="mono briefing-finding-no">{String(idx + 1).padStart(2, "0")}</span>
                    <span>{finding}</span>
                  </li>
                ))}
              </ol>
            </section>

            <hr className="hair" />

            <section className="briefing-metrics-grid">
              {selectedReport.metrics.map((metric) => (
                <article key={`${selectedReport.id}-m-${metric.label}`} className="briefing-metric-card">
                  <div className="mono briefing-metric-label">{metric.label}</div>
                  <div className={`serif briefing-metric-value ${toneClass(metric.tone)}`}>{metric.value}</div>
                  <div className="mono briefing-metric-sub">{metric.sub}</div>
                </article>
              ))}
            </section>

            <hr className="hair" />

            <section>
              <div className="briefing-section-label mono">§ Context</div>
              <p className="briefing-context">{selectedReport.context}</p>
              <div className="briefing-actions-row mono">
                <button
                  type="button"
                  className="briefing-link"
                  onClick={() => setExpandedBody((v) => !v)}
                >
                  {expandedBody ? "▸ Collapse dossier" : "▸ Read full dossier"}
                </button>
                <button
                  type="button"
                  className="briefing-link"
                  onClick={() => setInput((prev) => (prev ? prev : "Summarize key operational uncertainty in 3 bullets."))}
                >
                  ▸ Ask agent
                </button>
                <button
                  type="button"
                  className="briefing-link"
                  onClick={() => void promoteToWorldview(selectedReport)}
                >
                  ▸ Promote to Worldview
                </button>
              </div>
            </section>

            {expandedBody ? (
              <>
                <hr className="hair" />
                <section className="briefing-body-grid">
                  <div>
                    <h3 className="serif briefing-body-title">{selectedReport.body_title}</h3>
                    {selectedReport.body_paragraphs.map((paragraph, idx) => (
                      <p key={`${selectedReport.id}-p-${idx}`} className="briefing-body-paragraph">
                        {paragraph}
                      </p>
                    ))}
                  </div>
                  <aside>
                    <div className="briefing-section-label mono">§ Margin</div>
                    <div className="briefing-margin-list mono">
                      {selectedReport.margin.map((m) => (
                        <div key={`${selectedReport.id}-margin-${m.label}`}>
                          <span>{m.label}</span>
                          <span>{m.value}</span>
                        </div>
                      ))}
                    </div>
                    <div className="briefing-section-label mono" style={{ marginTop: "1rem" }}>
                      § Sources
                    </div>
                    <div className="briefing-source-list mono">
                      {selectedReport.sources.map((s) => (
                        <span key={`${selectedReport.id}-src-${s}`}>·{s}</span>
                      ))}
                    </div>
                  </aside>
                </section>
              </>
            ) : null}
          </div>
        )}
      </section>

      <aside className="briefing-col briefing-munin">
        <header className="briefing-munin-header">
          <h2 className="serif briefing-title" style={{ marginBottom: 2 }}>
            {muninOffline ? "§ Munin · silent." : "§ Munin · agent"}
          </h2>
          <div className="mono briefing-munin-state">
            {muninOffline
              ? `service unreachable · retry in ${retryIn}s`
              : muninLoading
                ? `thinking${currentAgent ? ` · ${currentAgent}` : ""}`
                : chatLoading
                  ? "syncing report channel"
                  : "report-scoped channel"}
          </div>
        </header>

        <div className="briefing-chat-list custom-scrollbar">
          {chatMessages.length === 0 && !muninLoading ? (
            <div className="briefing-chat-empty serif">No dialogue yet for this dossier.</div>
          ) : (
            chatMessages.map((msg) => (
              <article
                key={msg.id}
                className={`briefing-chat-item ${msg.role === "user" ? "is-user" : "is-munin"}`}
              >
                <div className="mono briefing-chat-meta">
                  <span>{(msg.role as MessageRole) === "user" ? "you" : msg.role}</span>
                  <span>{displayTs(msg.ts)}</span>
                </div>
                <p className={msg.role === "munin" ? "serif" : undefined}>{msg.text}</p>
                {msg.refs && msg.refs.length > 0 ? (
                  <div className="mono briefing-chat-refs">
                    {msg.refs.map((ref) => (
                      <span key={`${msg.id}-${ref}`}>·{ref}</span>
                    ))}
                  </div>
                ) : null}
              </article>
            ))
          )}
          {muninLoading && selectedReport ? (
            <div className="munin-loader-chat" data-testid="munin-thinking">
              <MuninLoader />
              <div className="munin-loader-chat-caption">
                § munin scanning
                {currentAgent ? ` · ${currentAgent}` : ""}
              </div>
            </div>
          ) : null}
        </div>

        <form className="briefing-input-wrap" onSubmit={(e) => void askMunin(e)}>
          <input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            disabled={muninOffline || muninLoading || !selectedReport}
            placeholder={muninOffline ? "▸ munin is resting" : "▸ ask Munin about this section…"}
            className="briefing-input"
          />
          <button
            type="submit"
            className="briefing-send"
            disabled={muninOffline || muninLoading || !input.trim() || !selectedReport}
          >
            send
          </button>
        </form>
      </aside>
    </div>
  );
}
