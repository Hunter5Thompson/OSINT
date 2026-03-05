import { useState } from "react";
import type { IntelAnalysis } from "../../types";

interface IntelPanelProps {
  loading: boolean;
  currentAgent: string | null;
  result: IntelAnalysis | null;
  error: string | null;
  history: IntelAnalysis[];
  onQuery: (query: string) => void;
}

export function IntelPanel({
  loading,
  currentAgent,
  result,
  error,
  history,
  onQuery,
}: IntelPanelProps) {
  const [queryText, setQueryText] = useState("");
  const [expanded, setExpanded] = useState(true);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (queryText.trim() && !loading) {
      onQuery(queryText.trim());
    }
  };

  return (
    <div className="absolute right-3 top-16 w-80 bg-black/85 border border-green-500/20 rounded font-mono text-xs z-40 backdrop-blur-sm max-h-[calc(100vh-120px)] flex flex-col">
      {/* Header */}
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full px-3 py-2 border-b border-green-500/20 text-green-400 font-bold tracking-wider flex items-center justify-between"
      >
        <span>INTELLIGENCE</span>
        <span className="text-green-500/40">{expanded ? "[-]" : "[+]"}</span>
      </button>

      {expanded && (
        <>
          {/* Query Input */}
          <form onSubmit={handleSubmit} className="p-3 border-b border-green-500/20">
            <div className="text-green-500/60 mb-2 text-[10px] tracking-widest">QUERY</div>
            <textarea
              value={queryText}
              onChange={(e) => setQueryText(e.target.value)}
              placeholder="Enter intelligence query..."
              maxLength={2000}
              className="w-full bg-black/50 border border-green-500/20 rounded px-2 py-1.5 text-green-300 placeholder:text-green-500/20 resize-none focus:outline-none focus:border-green-500/50"
              rows={3}
            />
            <button
              type="submit"
              disabled={loading || !queryText.trim()}
              className="mt-2 w-full py-1.5 bg-green-500/10 border border-green-500/30 text-green-400 rounded hover:bg-green-500/20 disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
            >
              {loading ? "PROCESSING..." : "RUN ANALYSIS"}
            </button>
          </form>

          {/* Status */}
          {loading && currentAgent && (
            <div className="px-3 py-2 border-b border-green-500/20">
              <div className="flex items-center gap-2">
                <span className="animate-pulse text-amber-400">&gt;</span>
                <span className="text-amber-400">{currentAgent}</span>
              </div>
            </div>
          )}

          {/* Error */}
          {error && (
            <div className="px-3 py-2 text-red-400 border-b border-red-500/20">
              ERROR: {error}
            </div>
          )}

          {/* Result */}
          {result && (
            <div className="p-3 border-b border-green-500/20 overflow-y-auto flex-shrink min-h-0">
              <div className="text-green-500/60 mb-1 text-[10px] tracking-widest">ANALYSIS</div>
              <div className="text-green-300 whitespace-pre-wrap mb-2">{result.analysis}</div>
              {result.threat_assessment && (
                <div className="mt-2">
                  <span className="text-green-500/60">THREAT: </span>
                  <span
                    className={
                      result.threat_assessment === "CRITICAL"
                        ? "text-red-400"
                        : result.threat_assessment === "HIGH"
                          ? "text-orange-400"
                          : "text-yellow-400"
                    }
                  >
                    {result.threat_assessment}
                  </span>
                </div>
              )}
              <div className="mt-1 text-green-500/40">
                Agents: {result.agent_chain.join(" → ")}
              </div>
            </div>
          )}

          {/* History */}
          {history.length > 0 && (
            <div className="p-3 overflow-y-auto flex-1 min-h-0">
              <div className="text-green-500/60 mb-2 text-[10px] tracking-widest">HISTORY</div>
              {history.slice(0, 10).map((item, i) => (
                <div
                  key={`${item.timestamp}-${i}`}
                  className="mb-2 pb-2 border-b border-green-500/10 last:border-0"
                >
                  <div className="text-green-400 truncate">{item.query}</div>
                  <div className="text-green-500/40 truncate">{item.analysis.slice(0, 80)}...</div>
                </div>
              ))}
            </div>
          )}
        </>
      )}
    </div>
  );
}
