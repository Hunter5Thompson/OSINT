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
  const seqRef = useRef(0);

  useEffect(() => {
    if (!eventId) {
      setDetail(null);
      setLoading(false);
      return;
    }
    const seq = ++seqRef.current;
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
        if (seq === seqRef.current) setLoading(false);
      });
    return () => ctrl.abort();
  }, [eventId]);

  if (!eventId) return null;

  const label = detail?.title || detail?.codebook_type || eventId;
  return (
    <section
      role="group"
      aria-label="event callout"
      style={{
        position: "absolute", top: 96, left: "50%", transform: "translateX(-50%)",
        minWidth: 240, maxWidth: 360, padding: "8px 12px",
        background: "var(--hl-panel-bg, rgba(10,10,12,0.82))",
        backdropFilter: "blur(var(--hl-panel-blur, 12px))",
        border: "1px solid var(--granite, #333)", borderRadius: 6, zIndex: 20,
        fontFamily: "var(--hl-font-mono, monospace)", fontSize: 11, color: "#ddd",
      }}
    >
      <div style={{ display: "flex", justifyContent: "space-between", gap: 8 }}>
        <strong>{loading ? "…" : label}</strong>
        <button type="button" aria-label="close callout" onClick={onClose}>×</button>
      </div>
      {detail ? (
        <>
          <div style={{ opacity: 0.7, marginTop: 4 }}>
            {detail.time.replace("T", " ").slice(0, 19)}Z · {detail.time_basis}
            {detail.source ? ` · ${detail.source}` : ""}
            {detail.severity ? ` · ${detail.severity}` : ""}
          </div>
          <button type="button" style={{ marginTop: 6 }} onClick={() => onInspect(detail)}>
            → Inspector
          </button>
        </>
      ) : null}
    </section>
  );
}
