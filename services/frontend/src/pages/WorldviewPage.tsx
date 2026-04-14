import { App } from "../App";

/**
 * Worldview — hosts the existing Cesium globe App untouched.
 * App.tsx remains the single source of truth for globe behaviour; this
 * page wrapper exists so the router can mount it at `/worldview` while
 * Tasks 2-7 refactor surrounding chrome.
 */
export function WorldviewPage() {
  return <App />;
}
