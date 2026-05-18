import { useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";

interface BandwidthGuardProps {
  sizeBytes: number;
  /** Fires exactly once when children are about to render — i.e. immediately
   *  on a fast connection, or after the user clicks "Load anyway". */
  onConfirm: () => void;
  onCancel: () => void;
  children: ReactNode;
}

interface ConnectionLike {
  effectiveType?: string;
}

function getEffectiveType(): string | undefined {
  const conn = (navigator as Navigator & { connection?: ConnectionLike }).connection;
  return conn?.effectiveType;
}

function isMetered(): boolean {
  const t = getEffectiveType();
  return t === "2g" || t === "slow-2g" || t === "3g";
}

export function BandwidthGuard({
  sizeBytes,
  onConfirm,
  onCancel,
  children,
}: BandwidthGuardProps) {
  const [confirmed, setConfirmed] = useState(false);
  const fastConnection = !isMetered();
  const allowed = fastConnection || confirmed;
  const firedRef = useRef(false);

  useEffect(() => {
    if (allowed && !firedRef.current) {
      firedRef.current = true;
      onConfirm();
    }
  }, [allowed, onConfirm]);

  if (allowed) return <>{children}</>;

  const sizeMb = Math.floor(sizeBytes / (1024 * 1024));
  return (
    <div role="dialog" aria-label="bandwidth confirm">
      <p>This scene is {sizeMb} MB and your connection appears metered.</p>
      <button onClick={() => setConfirmed(true)}>Load anyway</button>
      <button onClick={onCancel}>Cancel</button>
    </div>
  );
}
