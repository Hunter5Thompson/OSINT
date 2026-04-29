import { useState } from "react";
import { Outlet } from "react-router-dom";
import { TopBar } from "../components/hlidskjalf/TopBar";
import { IncidentToast } from "../components/hlidskjalf/IncidentToast";
import { IncidentProvider } from "../state/IncidentProvider";
import { useIncidents } from "../hooks/useIncidents";

/**
 * IncidentLayer — separate component so the SSE-bound state (read by
 * useIncidents) lives BELOW <IncidentProvider>. AppShell itself stays
 * outside the provider so it never reads stale context.
 */
function IncidentLayer({ children }: { children: React.ReactNode }) {
  const { active } = useIncidents();
  const [dismissedId, setDismissedId] = useState<string | null>(null);
  const toastIncident = active && active.id !== dismissedId ? active : null;

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100vh" }}>
      <TopBar warRoomActive={Boolean(active)} />
      <main
        style={{
          flex: 1,
          display: "flex",
          flexDirection: "column",
          minHeight: 0,
          position: "relative",
        }}
      >
        {children}
      </main>
      <IncidentToast
        incident={toastIncident}
        onDismiss={() => setDismissedId(active?.id ?? null)}
      />
    </div>
  );
}

export function AppShell() {
  return (
    <IncidentProvider>
      <IncidentLayer>
        <Outlet />
      </IncidentLayer>
    </IncidentProvider>
  );
}
