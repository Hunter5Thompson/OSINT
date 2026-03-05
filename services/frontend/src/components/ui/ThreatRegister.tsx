import type { Hotspot } from "../../types";

interface ThreatRegisterProps {
  hotspots: Hotspot[];
  onSelect: (hotspot: Hotspot) => void;
}

const THREAT_COLORS: Record<string, string> = {
  CRITICAL: "text-red-400 border-red-500/30 bg-red-500/5",
  HIGH: "text-orange-400 border-orange-500/30 bg-orange-500/5",
  ELEVATED: "text-yellow-400 border-yellow-500/30 bg-yellow-500/5",
  MODERATE: "text-green-400 border-green-500/30 bg-green-500/5",
};

const THREAT_DOTS: Record<string, string> = {
  CRITICAL: "bg-red-400",
  HIGH: "bg-orange-400",
  ELEVATED: "bg-yellow-400",
  MODERATE: "bg-green-400",
};

export function ThreatRegister({ hotspots, onSelect }: ThreatRegisterProps) {
  const sorted = [...hotspots].sort((a, b) => {
    const order = { CRITICAL: 0, HIGH: 1, ELEVATED: 2, MODERATE: 3 };
    return (order[a.threat_level] ?? 4) - (order[b.threat_level] ?? 4);
  });

  return (
    <div className="absolute left-3 bottom-14 w-56 max-h-64 bg-black/85 border border-green-500/20 rounded font-mono text-xs z-40 backdrop-blur-sm overflow-hidden flex flex-col">
      <div className="px-3 py-2 border-b border-green-500/20 text-green-400 font-bold tracking-wider">
        THREAT REGISTER
      </div>
      <div className="overflow-y-auto flex-1 custom-scrollbar">
        {sorted.map((h) => (
          <button
            key={h.id}
            onClick={() => onSelect(h)}
            className={`w-full text-left px-3 py-2 border-b border-green-500/10 hover:bg-green-500/5 transition-colors ${THREAT_COLORS[h.threat_level] ?? ""}`}
          >
            <div className="flex items-center gap-2">
              <span
                className={`w-2 h-2 rounded-full ${THREAT_DOTS[h.threat_level] ?? "bg-gray-400"} ${h.threat_level === "CRITICAL" ? "animate-pulse" : ""}`}
              />
              <span className="truncate">{h.name}</span>
            </div>
            <div className="text-[10px] text-green-500/40 ml-4 mt-0.5">{h.region}</div>
          </button>
        ))}
      </div>
    </div>
  );
}
