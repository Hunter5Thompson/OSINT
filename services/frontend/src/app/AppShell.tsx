import { Outlet } from "react-router-dom";
import { TopBar } from "../components/hlidskjalf/TopBar";

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
