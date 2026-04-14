import { Outlet } from "react-router-dom";
import { TopBar } from "../components/hlidskjalf/TopBar";

/**
 * AppShell — persistent chrome (TopBar) wrapping every routed page.
 * Task 7 will add full Hlíðskjalf Noir theming.
 */
export function AppShell() {
  return (
    <div style={{ display: "flex", flexDirection: "column", minHeight: "100vh" }}>
      <TopBar />
      <main style={{ flex: 1, display: "flex", flexDirection: "column" }}>
        <Outlet />
      </main>
    </div>
  );
}
