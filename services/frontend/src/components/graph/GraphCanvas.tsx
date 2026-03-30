import { useCallback, useRef, useState, useEffect } from "react";
// eslint-disable-next-line @typescript-eslint/no-explicit-any
import ForceGraph2D from "react-force-graph-2d";
import type { ForceGraphMethods } from "react-force-graph-2d";
import { type GraphNode, type GraphEdge, NODE_COLORS } from "./types";

interface GraphCanvasProps {
  nodes: GraphNode[];
  edges: GraphEdge[];
  onNodeClick: (node: GraphNode) => void;
  onNodeDoubleClick: (node: GraphNode) => void;
  hoveredNode: GraphNode | null;
  onNodeHover: (node: GraphNode | null) => void;
}

export default function GraphCanvas({
  nodes,
  edges,
  onNodeClick,
  onNodeDoubleClick,
  onNodeHover,
}: GraphCanvasProps) {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const fgRef = useRef<ForceGraphMethods<any, any> | undefined>(undefined);
  const containerRef = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(300);
  const [height, setHeight] = useState(400);

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const observer = new ResizeObserver((entries) => {
      for (const entry of entries) {
        setWidth(entry.contentRect.width);
        setHeight(entry.contentRect.height);
      }
    });
    observer.observe(el);
    // Set initial size
    setWidth(el.clientWidth);
    setHeight(el.clientHeight);
    return () => observer.disconnect();
  }, []);

  const graphData = {
    nodes: nodes.map((n) => ({ ...n })),
    links: edges.map((e) => ({
      source: e.source,
      target: e.target,
      label: e.relationship,
    })),
  };

  const nodeColor = useCallback(
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    (node: any): string => NODE_COLORS[(node as GraphNode).type] ?? (NODE_COLORS.unknown as string),
    [],
  );

  const nodeSize = useCallback(
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    (node: any): number => {
      const n = node as GraphNode;
      const degree = edges.filter(
        (e) => e.source === n.id || e.target === n.id,
      ).length;
      return Math.max(4, Math.min(12, 4 + degree));
    },
    [edges],
  );

  const nodeLabel = useCallback(
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    (node: any): string => {
      const n = node as GraphNode;
      return `${n.name} (${n.type})`;
    },
    [],
  );

  return (
    <div ref={containerRef} style={{ width: "100%", height: "100%", minHeight: 300 }}>
    {/* eslint-disable-next-line @typescript-eslint/no-explicit-any */}
    <ForceGraph2D<any, any>
      ref={fgRef}
      graphData={graphData}
      nodeColor={nodeColor}
      nodeVal={nodeSize}
      nodeLabel={nodeLabel}
      linkLabel="label"
      linkDirectionalArrowLength={3}
      linkDirectionalArrowRelPos={1}
      onNodeClick={(node) => onNodeClick(node as unknown as GraphNode)}
      onNodeRightClick={(node) => onNodeDoubleClick(node as unknown as GraphNode)}
      onNodeHover={(node) => onNodeHover(node ? (node as unknown as GraphNode) : null)}
      width={width}
      height={height}
      backgroundColor="#0f172a"
      linkColor={() => "#475569"}
      nodeCanvasObjectMode={() => "after"}
      nodeCanvasObject={(node, ctx, globalScale) => {
        const n = node as unknown as GraphNode & { x: number; y: number };
        const label = n.name;
        const fontSize = 10 / globalScale;
        ctx.font = `${fontSize}px Inter, sans-serif`;
        ctx.textAlign = "center";
        ctx.textBaseline = "middle";
        ctx.fillStyle = "#e2e8f0";
        ctx.fillText(label, n.x, n.y + 8);
      }}
    />
    </div>
  );
}
