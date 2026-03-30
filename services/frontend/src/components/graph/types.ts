export interface GraphNode {
  id: string;
  name: string;
  type: string;
  properties?: Record<string, unknown>;
  x?: number;
  y?: number;
}

export interface GraphEdge {
  source: string;
  target: string;
  relationship: string;
  properties?: Record<string, unknown>;
}

export interface GraphResponse {
  nodes: GraphNode[];
  edges: GraphEdge[];
  total_count: number;
}

export const NODE_COLORS: Record<string, string> = {
  person: "#3b82f6",
  organization: "#22c55e",
  location: "#ef4444",
  Event: "#f97316",
  military_unit: "#8b5cf6",
  weapon_system: "#ec4899",
  satellite: "#06b6d4",
  vessel: "#14b8a6",
  aircraft: "#eab308",
  unknown: "#6b7280",
};
