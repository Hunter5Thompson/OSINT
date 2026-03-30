import { type GraphNode, NODE_COLORS } from "./types";

interface NodeTooltipProps {
  node: GraphNode | null;
}

export default function NodeTooltip({ node }: NodeTooltipProps) {
  if (!node) return null;

  const color = NODE_COLORS[node.type] || NODE_COLORS.unknown;

  return (
    <div className="absolute top-4 right-4 bg-slate-800 border border-slate-600 rounded-lg p-3 text-sm text-slate-200 max-w-xs shadow-lg">
      <div className="flex items-center gap-2 mb-1">
        <span className="w-3 h-3 rounded-full inline-block" style={{ backgroundColor: color }} />
        <span className="font-semibold">{node.name}</span>
      </div>
      <div className="text-slate-400 text-xs">{node.type}</div>
      {node.properties && Object.keys(node.properties).length > 0 && (
        <div className="mt-2 text-xs text-slate-400">
          {Object.entries(node.properties).map(([k, v]) => (
            <div key={k}>
              <span className="text-slate-500">{k}:</span> {String(v)}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
