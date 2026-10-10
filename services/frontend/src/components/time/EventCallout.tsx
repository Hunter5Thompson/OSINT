import { useEffect, useRef, useState } from "react";
import type { TimelineEventDetail } from "../../types";
import { getEventDetail } from "../../services/api";

interface EventCalloutProps {
  eventId: string | null;
  onClose: () => void;
  onInspect: (d: TimelineEventDetail) => void;
}

export function EventCallout({ eventId, onClose, onInspect }: EventCalloutProps) {
  const [detail, setDetail] = useState<TimelineEventDetail | null>(null);
  const [loading, setLoading] = useState(false);
  const [failed, setFailed] = useState(false);
  const seqRef = useRef(0);

  useEffect(() => {
    const seq = ++seqRef.current;
    setDetail(null);
    setFailed(false);
    if (!eventId) {
      setLoading(false);
      return;
    }
    const ctrl = new AbortController();
    setLoading(true);
    void getEventDetail(eventId, ctrl.signal)
      .then((d) => {
        if (seq === seqRef.current) {
          setDetail(d);
          setLoading(false);
        }
      })
      .catch(() => {
        if (seq === seqRef.current) {
          setLoading(false);
          setFailed(true);
        }
      });
    return () => { ++seqRef.current; ctrl.abort(); };
  }, [eventId]);

  if (!eventId) return null;

  const currentDetail = detail?.id === eventId ? detail : null;
  const label = currentDetail?.title || currentDetail?.codebook_type || eventId;
  const mono = '"Martian Mono", ui-monospace, "SFMono-Regular", Consolas, monospace';
  const btn: React.CSSProperties = {
    background: "transparent",
    border: "1px solid var(--granite, #2a2720)",
    color: "var(--stone, #958a7a)",
    font: "inherit",
    fontSize: 10,
    textTransform: "uppercase",
    letterSpacing: "0.08em",
    padding: "2px 8px",
    borderRadius: 2,
    cursor: "pointer",
  };
  return (
    <section
      role="group"
      aria-label="event callout"
      style={{
        position: "absolute", top: 96, left: "50%", transform: "translateX(-50%)",
        minWidth: 248, maxWidth: 360, padding: "10px 12px",
        background: "var(--hl-panel-bg, rgba(18,17,14,0.84))",
        backdropFilter: "blur(12px)",
        border: "1px solid var(--granite, #2a2720)", borderRadius: 4, zIndex: 20,
        fontFamily: mono, fontSize: 11, color: "var(--bone, #d4cdc0)",
        boxShadow: "0 6px 24px rgba(0,0,0,0.45)",
      }}
    >
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", gap: 8 }}>
        <strong style={{ color: "var(--parchment, #e8e2d4)", fontWeight: 600 }}>
          {loading ? "…" : label}
        </strong>
        <button
          type="button"
          aria-label="close callout"
          onClick={onClose}
          style={{ ...btn, padding: "0 6px", lineHeight: 1.4 }}
        >
          ×
        </button>
      </div>
      {failed ? <div role="status">Detail nicht verfügbar.</div> : null}
      {currentDetail ? (
        <>
          <div style={{ color: "var(--ash, #6b6358)", marginTop: 6, letterSpacing: "0.02em" }}>
            {currentDetail.time.replace("T", " ").slice(0, 19)}Z · {currentDetail.time_basis}
            {currentDetail.source ? ` · ${currentDetail.source}` : ""}
            {currentDetail.severity ? ` · ${currentDetail.severity}` : ""}
          </div>
          <button type="button" style={{ ...btn, marginTop: 8 }} onClick={() => onInspect(currentDetail)}>
            → Inspector
          </button>
        </>
      ) : null}
    </section>
  );
}
