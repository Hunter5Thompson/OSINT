import { createRoot } from "react-dom/client";
import { RouterProvider } from "react-router-dom";
import { router } from "./app/router";
import "./index.css";

// NOTE: StrictMode temporarily disabled for S1 visual check.
// Cesium 1.135 + React 19 double-invoke collide in existing GlobeViewer/SatelliteLayer
// (pre-existing on main; not introduced by S1). Worldview hardening is S2 scope.
const root = document.getElementById("root");
if (!root) throw new Error("Root element not found");

createRoot(root).render(<RouterProvider router={router} />);
