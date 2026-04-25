import { useEffect, useState } from "react";

export function formatTPlus(seconds: number): string {
  const safe = Math.max(0, Math.floor(seconds));
  const days = Math.floor(safe / 86_400);
  const rem = safe - days * 86_400;
  const hh = Math.floor(rem / 3600);
  const mm = Math.floor((rem - hh * 3600) / 60);
  const ss = rem - hh * 3600 - mm * 60;
  const pad = (n: number) => (n < 10 ? `0${n}` : String(n));
  if (days > 0) return `T+${days}d.${pad(hh)}:${pad(mm)}`;
  return `T+${pad(hh)}:${pad(mm)}:${pad(ss)}`;
}

export function useTPlus(triggerIso: string | null): string {
  const [now, setNow] = useState<number>(() => Date.now());
  useEffect(() => {
    const id = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(id);
  }, []);
  if (!triggerIso) return formatTPlus(0);
  const triggerMs = Date.parse(triggerIso);
  if (Number.isNaN(triggerMs)) return formatTPlus(0);
  return formatTPlus((now - triggerMs) / 1000);
}
