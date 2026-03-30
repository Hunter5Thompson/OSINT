import { useState } from "react";
import { IntelPanel } from "./IntelPanel";
import EntityExplorer from "../graph/EntityExplorer";
import type { IntelAnalysis } from "../../types";

type TabId = "intel" | "graph";

interface RightPanelProps {
  // Intel props
  loading: boolean;
  currentAgent: string | null;
  result: IntelAnalysis | null;
  error: string | null;
  history: IntelAnalysis[];
  onQuery: (query: string, useLegacy: boolean) => void;
}

export function RightPanel({
  loading,
  currentAgent,
  result,
  error,
  history,
  onQuery,
}: RightPanelProps) {
  const [activeTab, setActiveTab] = useState<TabId>("intel");

  return (
    <div className="absolute right-3 top-16 w-80 z-40 max-h-[calc(100vh-120px)] flex flex-col">
      {/* Tab Bar */}
      <div className="flex bg-black/85 border border-green-500/20 border-b-0 rounded-t font-mono text-[10px] tracking-widest backdrop-blur-sm">
        <button
          onClick={() => setActiveTab("intel")}
          className={`flex-1 px-3 py-2 text-center transition-colors ${
            activeTab === "intel"
              ? "text-green-400 border-b-2 border-green-400 bg-black/50"
              : "text-green-400/40 hover:text-green-400/60"
          }`}
        >
          INTEL
        </button>
        <button
          onClick={() => setActiveTab("graph")}
          className={`flex-1 px-3 py-2 text-center transition-colors ${
            activeTab === "graph"
              ? "text-blue-400 border-b-2 border-blue-500 bg-black/50"
              : "text-green-400/40 hover:text-green-400/60"
          }`}
        >
          GRAPH
        </button>
      </div>

      {/* Tab Content */}
      <div className="flex-1 min-h-0 overflow-hidden">
        {activeTab === "intel" ? (
          <IntelPanel
            loading={loading}
            currentAgent={currentAgent}
            result={result}
            error={error}
            history={history}
            onQuery={onQuery}
          />
        ) : (
          <div className="bg-black/85 border border-green-500/20 border-t-0 rounded-b backdrop-blur-sm overflow-hidden">
            <EntityExplorer apiBaseUrl="/api/v1/graph" />
          </div>
        )}
      </div>
    </div>
  );
}
