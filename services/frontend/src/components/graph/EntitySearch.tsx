import { useState, useCallback } from "react";
import type { GraphNode, GraphResponse } from "./types";

interface EntitySearchProps {
  apiBaseUrl: string;
  onSelect: (entity: GraphNode) => void;
}

export default function EntitySearch({ apiBaseUrl, onSelect }: EntitySearchProps) {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<GraphNode[]>([]);
  const [loading, setLoading] = useState(false);

  const search = useCallback(
    async (q: string) => {
      if (q.length < 2) {
        setResults([]);
        return;
      }
      setLoading(true);
      try {
        const resp = await fetch(`${apiBaseUrl}/search?q=${encodeURIComponent(q)}&limit=10`);
        const data: GraphResponse = await resp.json();
        setResults(data.nodes);
      } catch {
        setResults([]);
      } finally {
        setLoading(false);
      }
    },
    [apiBaseUrl],
  );

  return (
    <div className="relative">
      <input
        type="text"
        value={query}
        onChange={(e) => {
          setQuery(e.target.value);
          search(e.target.value);
        }}
        placeholder="Search entities..."
        className="w-full px-3 py-2 bg-slate-800 border border-slate-600 rounded text-sm text-slate-200 placeholder-slate-500 focus:border-blue-500 focus:outline-none"
      />
      {results.length > 0 && (
        <ul className="absolute z-10 w-full mt-1 bg-slate-800 border border-slate-600 rounded shadow-lg max-h-48 overflow-y-auto">
          {results.map((r) => (
            <li
              key={r.id}
              className="px-3 py-2 text-sm text-slate-200 hover:bg-slate-700 cursor-pointer"
              onClick={() => {
                onSelect(r);
                setQuery(r.name);
                setResults([]);
              }}
            >
              <span className="font-medium">{r.name}</span>
              <span className="ml-2 text-xs text-slate-400">{r.type}</span>
            </li>
          ))}
        </ul>
      )}
      {loading && (
        <div className="absolute right-3 top-2.5 text-xs text-slate-400">...</div>
      )}
    </div>
  );
}
