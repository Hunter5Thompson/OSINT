import { Outlet } from "react-router-dom";
import { TopBar } from "../components/hlidskjalf/TopBar";

/**
 * AppShell — persistent chrome (TopBar) wrapping every routed page.
 *
 * TopBar is always visible so navigation remains available on every route.
 */
export function AppShell() {
  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100vh" }}>
      <TopBar />
      <main
        style={{
          flex: 1,
          display: "flex",
          flexDirection: "column",
          minHeight: 0,
          position: "relative",
        }}
      >
        <Outlet />
      </main>
    </div>
  );
}
