import { useState, useEffect, useRef } from "react";
import type { DataFreshness } from "../../types";

interface StatusBarProps {
  freshness: DataFreshness;
  flightCount: number;
  satelliteCount: number;
  earthquakeCount: number;
  vesselCount: number;
  eventCount: number;
  cableCount: number;
  pipelineCount: number;
}

function formatAge(date: Date | null): string {
  if (!date) return "--";
  const seconds = Math.floor((Date.now() - date.getTime()) / 1000);
  if (seconds < 60) return `${seconds}s`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m`;
  return `${Math.floor(seconds / 3600)}h`;
}

export function StatusBar({
  freshness,
  flightCount,
  satelliteCount,
  earthquakeCount,
  vesselCount,
  eventCount,
  cableCount,
  pipelineCount,
}: StatusBarProps) {
  const [fps, setFps] = useState(0);
  const frameRef = useRef(0);
  const lastTimeRef = useRef(performance.now());

  useEffect(() => {
    let animId: number;
    const measure = () => {
      frameRef.current++;
      const now = performance.now();
      if (now - lastTimeRef.current >= 1000) {
        setFps(frameRef.current);
        frameRef.current = 0;
        lastTimeRef.current = now;
      }
      animId = requestAnimationFrame(measure);
    };
    animId = requestAnimationFrame(measure);
    return () => cancelAnimationFrame(animId);
  }, []);

  const fpsColor = fps >= 50 ? "text-green-400" : fps >= 30 ? "text-yellow-400" : "text-red-400";

  return (
    <div className="absolute bottom-0 left-0 right-0 h-8 bg-black/80 border-t border-green-500/20 flex items-center justify-between px-4 font-mono text-[10px] z-50 backdrop-blur-sm">
      {/* Data Counts */}
      <div className="flex items-center gap-4 text-green-500/60">
        <span>
          FLIGHTS <span className="text-green-300">{flightCount.toLocaleString()}</span>
          <span className="text-green-500/30 ml-1">[{formatAge(freshness.flights)}]</span>
        </span>
        <span>
          SATS <span className="text-green-300">{satelliteCount.toLocaleString()}</span>
          <span className="text-green-500/30 ml-1">[{formatAge(freshness.satellites)}]</span>
        </span>
        <span>
          QUAKES <span className="text-green-300">{earthquakeCount}</span>
          <span className="text-green-500/30 ml-1">[{formatAge(freshness.earthquakes)}]</span>
        </span>
        <span>
          SHIPS <span className="text-green-300">{vesselCount}</span>
          <span className="text-green-500/30 ml-1">[{formatAge(freshness.vessels)}]</span>
        </span>
        <span>
          EVENTS <span className="text-green-300">{eventCount}</span>
          <span className="text-green-500/30 ml-1">[{formatAge(freshness.events)}]</span>
        </span>
        <span>
          CABLES <span className="text-green-300">{cableCount}</span>
          <span className="text-green-500/30 ml-1">[{formatAge(freshness.cables)}]</span>
        </span>
        <span>
          PIPES <span className="text-yellow-400">{pipelineCount}</span>
          <span className="text-green-500/30 ml-1">[{formatAge(freshness.pipelines)}]</span>
        </span>
      </div>

      {/* FPS + Status */}
      <div className="flex items-center gap-4">
        <span className="text-green-500/40">
          SYS <span className="text-green-400">NOMINAL</span>
        </span>
        <span className={fpsColor}>{fps} FPS</span>
      </div>
    </div>
  );
}
