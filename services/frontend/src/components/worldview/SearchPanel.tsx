import { useEffect, useRef, useState } from "react";
import type * as Cesium from "cesium";

export interface GraphNode {
  id: string;
  name: string;
  type: string;
}

interface GraphSearchResponse {
  nodes: GraphNode[];
  total_count: number;
}

export interface SearchPanelProps {
  viewer: Cesium.Viewer | null;
}

export function SearchPanel(_props: SearchPanelProps) {
  const [q, setQ] = useState("");
  const [results, setResults] = useState<GraphNode[] | null>(null);
  const [loading, setLoading] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  useEffect(() => {
    if (q.trim().length < 2) {
      setResults(null);
      setLoading(false);
      return;
    }
    let cancelled = false;
    const t = setTimeout(async () => {
      setLoading(true);
      try {
        const res = await fetch(
          `/api/graph/search?q=${encodeURIComponent(q.trim())}&limit=20`,
        );
        if (!res.ok) throw new Error("search failed");
        const data = (await res.json()) as GraphSearchResponse;
        if (cancelled) return;
        setResults(data.nodes);
      } catch {
        if (!cancelled) setResults([]);
      } finally {
        if (!cancelled) setLoading(false);
      }
    }, 180);
    return () => {
      cancelled = true;
      clearTimeout(t);
    };
  }, [q]);

  return (
    <div>
      <input
        ref={inputRef}
        value={q}
        onChange={(e) => setQ(e.target.value)}
        placeholder="search entities…"
        style={{
          width: "100%",
          background: "transparent",
          border: "none",
          borderBottom: "1px solid var(--granite)",
          color: "var(--bone)",
          fontFamily: "'Instrument Serif', serif",
          fontStyle: "italic",
          fontSize: "14px",
          padding: "6px 0",
          outline: "none",
        }}
      />
      <div style={{ marginTop: 10, minHeight: 24 }}>
        {loading && (
          <span className="mono" style={{ color: "var(--ash)", fontSize: 10 }}>
            § searching…
          </span>
        )}
        {!loading && results?.length === 0 && (
          <span className="mono" style={{ color: "var(--ash)", fontSize: 10 }}>
            — no matches —
          </span>
        )}
        {!loading && results && results.length > 0 && (
          <ul style={{ listStyle: "none", padding: 0, margin: 0 }}>
            {results.map((node) => (
              <li key={node.id} style={{ padding: "6px 0", display: "flex", flexDirection: "column", gap: 2 }}>
                <span
                  className="mono"
                  style={{
                    color: "var(--ash)",
                    fontSize: 10,
                    letterSpacing: "0.22em",
                    textTransform: "uppercase",
                  }}
                >
                  § {node.type}
                </span>
                <span
                  style={{
                    color: "var(--bone)",
                    fontFamily: "'Instrument Serif', serif",
                    fontStyle: "italic",
                    fontSize: 13,
                  }}
                >
                  {node.name}
                </span>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
