import { useState, useEffect } from "react";

interface TimezoneDisplay {
  label: string;
  timezone: string;
}

const TIMEZONES: TimezoneDisplay[] = [
  { label: "UTC", timezone: "UTC" },
  { label: "LOCAL", timezone: Intl.DateTimeFormat().resolvedOptions().timeZone },
  { label: "DC", timezone: "America/New_York" },
  { label: "MSK", timezone: "Europe/Moscow" },
  { label: "BJS", timezone: "Asia/Shanghai" },
];

function formatTime(date: Date, tz: string): string {
  return date.toLocaleTimeString("en-GB", {
    timeZone: tz,
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  });
}

function formatDate(date: Date): string {
  return date.toLocaleDateString("en-GB", {
    timeZone: "UTC",
    year: "numeric",
    month: "short",
    day: "2-digit",
  });
}

export function ClockBar() {
  const [now, setNow] = useState(new Date());

  useEffect(() => {
    const timer = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(timer);
  }, []);

  return (
    <div className="absolute top-0 left-0 right-0 h-10 bg-black/80 border-b border-green-500/20 flex items-center justify-between px-4 font-mono text-xs z-50 backdrop-blur-sm">
      {/* Title */}
      <div className="flex items-center gap-3">
        <span className="text-green-400 font-bold tracking-wider">WORLDVIEW</span>
        <span className="text-green-500/30">|</span>
        <span className="text-green-500/50">{formatDate(now)}</span>
      </div>

      {/* Timezone Clocks */}
      <div className="flex items-center gap-4">
        {TIMEZONES.map((tz) => (
          <div key={tz.label} className="flex items-center gap-1.5">
            <span className="text-green-500/40">{tz.label}</span>
            <span className="text-green-300 tabular-nums">{formatTime(now, tz.timezone)}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
