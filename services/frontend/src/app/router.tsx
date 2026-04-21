import {
  createBrowserRouter,
  redirect,
  type LoaderFunctionArgs,
  type RouteObject,
} from "react-router-dom";
import { AppShell } from "./AppShell";
import { LandingPage } from "../pages/LandingPage";
import { WorldviewPage } from "../pages/WorldviewPage";
import { BriefingPage } from "../pages/BriefingPage";
import { WarRoomPage } from "../pages/WarRoomPage";

/**
 * Legacy query migration loader for `/`.
 *
 * Before the 4-layer restructure the globe was mounted at `/` and consumers
 * deep-linked via `?entity=...` / `?layer=...`. Those links now live on
 * `/worldview`, so any request to `/` carrying either query param is forwarded
 * with the full query string preserved.
 */
function rootLoader({ request }: LoaderFunctionArgs) {
  const url = new URL(request.url);
  if (url.searchParams.has("entity") || url.searchParams.has("layer")) {
    return redirect(`/worldview${url.search}`);
  }
  return null;
}

export const routes: RouteObject[] = [
  {
    element: <AppShell />,
    children: [
      { path: "/", loader: rootLoader, element: <LandingPage /> },
      {
        path: "/worldview",
        element: <WorldviewPage />,
      },
      { path: "/briefing", element: <BriefingPage /> },
      { path: "/briefing/:reportId", element: <BriefingPage /> },
      { path: "/warroom", element: <WarRoomPage /> },
      { path: "/warroom/:incidentId", element: <WarRoomPage /> },
    ],
  },
];

export const router = createBrowserRouter(routes);
