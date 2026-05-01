import { useEffect, useRef, useState } from "react";
import type * as Cesium from "cesium";

export interface GraphNode {
  id: string;
  name: string;
  type: string;
  properties?: { lat?: number; lon?: number; [key: string]: unknown };
}

interface GraphSearchResponse {
  nodes: GraphNode[];
}

export interface SearchPanelProps {
  viewer: Cesium.Viewer | null;
  initialQuery?: string;
  onAccept?: (node: GraphNode) => void;
}

export function SearchPanel({ viewer: _viewer, initialQuery = "", onAccept }: SearchPanelProps) {
  const [query, setQuery] = useState(initialQuery);
  const [loading, setLoading] = useState(false);
  const [results, setResults] = useState<GraphNode[] | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  useEffect(() => {
    setQuery(initialQuery);
  }, [initialQuery]);

  useEffect(() => {
    const normalized = query.trim();
    if (normalized.length < 2) {
      setResults(null);
      setLoading(false);
      return;
    }

    let cancelled = false;
    const controller = new AbortController();
    const timeout = window.setTimeout(async () => {
      setLoading(true);
      try {
        let res = await fetch(`/api/graph/search?q=${encodeURIComponent(normalized)}&limit=20`, {
          signal: controller.signal,
        });
        if (res.status === 404) {
          res = await fetch(`/api/v1/graph/search?q=${encodeURIComponent(normalized)}&limit=20`, {
            signal: controller.signal,
          });
        }
        if (!res.ok) {
          throw new Error(`search failed: ${res.status}`);
        }
        const data = (await res.json()) as GraphSearchResponse;
        if (!cancelled) {
          setResults(data.nodes);
        }
      } catch {
        if (!cancelled) {
          setResults([]);
        }
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    }, 180);

    return () => {
      cancelled = true;
      controller.abort();
      window.clearTimeout(timeout);
    };
  }, [query]);

  return (
    <div>
      <input
        ref={inputRef}
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        placeholder="search entities..."
        style={{
          width: "100%",
          background: "transparent",
          border: "none",
          borderBottom: "1px solid var(--granite)",
          color: "var(--parchment)",
          fontFamily: '"Instrument Serif", "Times New Roman", serif',
          fontStyle: "italic",
          fontSize: "1rem",
          outline: "none",
          padding: "0.2rem 0",
        }}
      />

      <div style={{ marginTop: "0.7rem", minHeight: 28 }}>
        {loading ? (
          <span className="mono" style={{ color: "var(--ash)", fontSize: "0.66rem" }}>
            § searching…
          </span>
        ) : null}

        {!loading && results?.length === 0 ? (
          <span className="mono" style={{ color: "var(--ash)", fontSize: "0.66rem" }}>
            — no matches —
          </span>
        ) : null}

        {!loading && results && results.length > 0 ? (
          <ul style={{ listStyle: "none", margin: 0, padding: 0, maxHeight: 220, overflowY: "auto" }}>
            {results.map((node) => (
              <li
                key={node.id}
                onClick={() => onAccept?.(node)}
                style={{ cursor: "pointer", padding: "0.42rem 0", borderBottom: "1px solid rgba(107,99,88,0.25)" }}
              >
                <button
                  type="button"
                  style={{
                    border: "none",
                    background: "transparent",
                    color: "inherit",
                    textAlign: "left",
                    width: "100%",
                    cursor: "pointer",
                    padding: 0,
                  }}
                >
                  <div
                    className="mono"
                    style={{
                      color: "var(--stone)",
                      fontSize: "0.62rem",
                      letterSpacing: "0.12em",
                      textTransform: "uppercase",
                    }}
                  >
                    {`§ ${node.type}`}
                  </div>
                  <div
                    style={{
                      marginTop: "0.2rem",
                      color: "var(--parchment)",
                      fontFamily: '"Instrument Serif", "Times New Roman", serif',
                      fontStyle: "italic",
                      fontSize: "0.98rem",
                    }}
                  >
                    {node.name}
                  </div>
                </button>
              </li>
            ))}
          </ul>
        ) : null}
      </div>
    </div>
  );
}
