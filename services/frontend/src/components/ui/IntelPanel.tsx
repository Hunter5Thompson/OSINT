import { useState } from "react";
import type { IntelAnalysis } from "../../types";

const MODE_LABELS: Record<string, string> = {
  react: "ReAct",
  legacy: "Legacy",
  legacy_fallback: "Fallback",
  error: "Error",
};

const MODE_COLORS: Record<string, string> = {
  react: "bg-blue-500/20 text-blue-400 border-blue-500/30",
  legacy: "bg-amber-500/20 text-amber-400 border-amber-500/30",
  legacy_fallback: "bg-red-500/20 text-red-400 border-red-500/30",
  error: "bg-red-600/20 text-red-500 border-red-600/30",
};

interface IntelPanelProps {
  loading: boolean;
  currentAgent: string | null;
  result: IntelAnalysis | null;
  error: string | null;
  history: IntelAnalysis[];
  onQuery: (query: string, useLegacy: boolean) => void;
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
  const [useLegacy, setUseLegacy] = useState(false);
  const [expanded, setExpanded] = useState(true);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (queryText.trim() && !loading) {
      onQuery(queryText.trim(), useLegacy);
    }
  };

  // Tool chain: prefer tool_trace, fall back to agent_chain
  const toolChain: string[] = result?.tool_trace?.length
    ? result.tool_trace.map((t) => t.tool_name)
    : result?.agent_chain?.length
      ? result.agent_chain
      : [];

  return (
    <div className="bg-black/85 border border-green-500/20 rounded font-mono text-xs backdrop-blur-sm flex flex-col overflow-hidden">
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
            <div className="flex items-center justify-between mt-2">
              <label className="flex items-center gap-1.5 text-green-500/50 cursor-pointer select-none">
                <input
                  type="checkbox"
                  checked={useLegacy}
                  onChange={(e) => setUseLegacy(e.target.checked)}
                  className="accent-amber-500 w-3 h-3"
                />
                <span className="text-[10px]">LEGACY MODE</span>
              </label>
              <button
                type="submit"
                disabled={loading || !queryText.trim()}
                className="py-1.5 px-4 bg-green-500/10 border border-green-500/30 text-green-400 rounded hover:bg-green-500/20 disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
              >
                {loading ? "PROCESSING..." : "RUN ANALYSIS"}
              </button>
            </div>
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
              {/* Mode Badge + Threat */}
              <div className="flex items-center gap-2 mb-2">
                {result.mode && MODE_LABELS[result.mode] && (
                  <span className={`px-2 py-0.5 rounded text-[10px] font-mono uppercase border ${MODE_COLORS[result.mode] ?? ""}`}>
                    {MODE_LABELS[result.mode]}
                  </span>
                )}
                {result.threat_assessment && (
                  <span
                    className={`text-[10px] font-bold ${
                      result.threat_assessment === "CRITICAL"
                        ? "text-red-400"
                        : result.threat_assessment === "HIGH"
                          ? "text-orange-400"
                          : result.threat_assessment === "ELEVATED"
                            ? "text-yellow-400"
                            : "text-green-400"
                    }`}
                  >
                    {result.threat_assessment}
                  </span>
                )}
              </div>

              {/* Tool Chain */}
              {toolChain.length > 0 && (
                <div className="text-[10px] text-green-400/60 font-mono mb-2">
                  {toolChain.join(" → ")}
                </div>
              )}

              <div className="text-green-500/60 mb-1 text-[10px] tracking-widest">ANALYSIS</div>
              <div className="text-green-300 whitespace-pre-wrap">{result.analysis}</div>
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
