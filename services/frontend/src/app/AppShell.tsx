import { Outlet, useLocation } from "react-router-dom";
import { TopBar } from "../components/hlidskjalf/TopBar";

/**
 * AppShell — persistent chrome (TopBar) wrapping every routed page.
 *
 * S1 temporary: /worldview keeps the legacy App.tsx fullscreen chrome
 * (StatusBar + ClockBar are position:fixed top:0 and collide with our
 * TopBar; App.tsx also expects a 100vh parent for Cesium to size itself).
 * S2 "Worldview-Port" will rewrite the chrome so the TopBar can coexist.
 */
export function AppShell() {
  const location = useLocation();
  const isWorldview = location.pathname.startsWith("/worldview");

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100vh" }}>
      {!isWorldview && <TopBar />}
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
