import { useState, useCallback, useEffect } from "react";
import GraphCanvas from "./GraphCanvas";
import EntitySearch from "./EntitySearch";
import NodeTooltip from "./NodeTooltip";
import type { GraphNode, GraphEdge, GraphResponse } from "./types";

interface EntityExplorerProps {
  initialEntity?: string;
  apiBaseUrl?: string;
}

const ENTITY_TYPES = ["all", "person", "organization", "location", "military_unit", "weapon_system", "satellite", "vessel", "aircraft"];

export default function EntityExplorer({
  initialEntity,
  apiBaseUrl = "/api/v1/graph",
}: EntityExplorerProps) {
  const [nodes, setNodes] = useState<GraphNode[]>([]);
  const [edges, setEdges] = useState<GraphEdge[]>([]);
  const [hoveredNode, setHoveredNode] = useState<GraphNode | null>(null);
  const [typeFilter, setTypeFilter] = useState("all");
  const [expandedNodes, setExpandedNodes] = useState<Set<string>>(new Set());
  const [loading, setLoading] = useState(false);

  const loadNetwork = useCallback(
    async (entityName: string) => {
      setLoading(true);
      try {
        const resp = await fetch(`${apiBaseUrl}/network/${encodeURIComponent(entityName)}?limit=50`);
        const data: GraphResponse = await resp.json();
        setNodes(data.nodes);
        setEdges(data.edges);
        setExpandedNodes(new Set([entityName]));
      } catch (err) {
        console.error("Failed to load network:", err);
      } finally {
        setLoading(false);
      }
    },
    [apiBaseUrl],
  );

  useEffect(() => {
    if (initialEntity) {
      loadNetwork(initialEntity);
    }
  }, [initialEntity, loadNetwork]);

  const handleNodeClick = useCallback(
    async (node: GraphNode) => {
      if (expandedNodes.has(node.name)) return;

      setLoading(true);
      try {
        const resp = await fetch(`${apiBaseUrl}/neighbors/${encodeURIComponent(node.name)}?limit=30`);
        const data: GraphResponse = await resp.json();

        setNodes((prev) => {
          const existing = new Set(prev.map((n) => n.id));
          const newNodes = data.nodes.filter((n) => !existing.has(n.id));
          return [...prev, ...newNodes];
        });
        setEdges((prev) => {
          const existingKeys = new Set(prev.map((e) => `${e.source}-${e.relationship}-${e.target}`));
          const newEdges = data.edges.filter((e) => !existingKeys.has(`${e.source}-${e.relationship}-${e.target}`));
          return [...prev, ...newEdges];
        });
        setExpandedNodes((prev) => new Set([...prev, node.name]));
      } catch (err) {
        console.error("Failed to expand node:", err);
      } finally {
        setLoading(false);
      }
    },
    [apiBaseUrl, expandedNodes],
  );

  const handleNodeDoubleClick = useCallback(
    (node: GraphNode) => {
      if (expandedNodes.has(node.name) && expandedNodes.size > 1) {
        setExpandedNodes((prev) => {
          const next = new Set(prev);
          next.delete(node.name);
          return next;
        });
      }
    },
    [expandedNodes],
  );

  const filteredNodes = typeFilter === "all" ? nodes : nodes.filter((n) => n.type === typeFilter);
  const filteredNodeIds = new Set(filteredNodes.map((n) => n.id));
  const filteredEdges = edges.filter((e) => filteredNodeIds.has(e.source) && filteredNodeIds.has(e.target));

  return (
    <div className="relative bg-slate-900 rounded-lg border border-slate-700 overflow-hidden">
      <div className="flex gap-3 p-3 border-b border-slate-700">
        <div className="flex-1">
          <EntitySearch apiBaseUrl={apiBaseUrl} onSelect={(n) => loadNetwork(n.name)} />
        </div>
        <select
          value={typeFilter}
          onChange={(e) => setTypeFilter(e.target.value)}
          className="px-3 py-2 bg-slate-800 border border-slate-600 rounded text-sm text-slate-200"
        >
          {ENTITY_TYPES.map((t) => (
            <option key={t} value={t}>
              {t === "all" ? "All types" : t}
            </option>
          ))}
        </select>
      </div>

      <div className="relative">
        {loading && (
          <div className="absolute inset-0 bg-slate-900/50 flex items-center justify-center z-10">
            <span className="text-slate-400 text-sm">Loading...</span>
          </div>
        )}
        <GraphCanvas
          nodes={filteredNodes}
          edges={filteredEdges}
          onNodeClick={handleNodeClick}
          onNodeDoubleClick={handleNodeDoubleClick}
          hoveredNode={hoveredNode}
          onNodeHover={setHoveredNode}
        />
        <NodeTooltip node={hoveredNode} />
      </div>

      <div className="flex justify-between px-3 py-1 border-t border-slate-700 text-xs text-slate-500">
        <span>{filteredNodes.length} nodes, {filteredEdges.length} edges</span>
        <span>Click to expand, right-click to collapse</span>
      </div>
    </div>
  );
}
