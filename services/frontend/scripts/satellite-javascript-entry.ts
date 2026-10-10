/** Narrow build boundary for satellite.js 7.1's optional WASM barrel export.
 * Keep the pinned upstream JavaScript implementation unchanged. No dependency
 * files are rewritten, and an unexpected entry shape fails the build.
 * Remove when a qualified upstream public JS entry becomes available (#191).
 */
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import type { Plugin } from "vite";

const OPTIONAL_WASM_EXPORT = "export * from './wasm/index.js';";

export function javascriptEntrySource(source: string): string {
  if (source.split(OPTIONAL_WASM_EXPORT).length !== 2) {
    throw new Error("Unexpected satellite.js entry; requalify the JavaScript build boundary");
  }
  return source.replace(OPTIONAL_WASM_EXPORT, "");
}

export function satelliteJavascriptEntry(): Plugin {
  const entry = fileURLToPath(new URL("../node_modules/satellite.js/dist/index.js", import.meta.url));
  const packagePath = fileURLToPath(new URL("../node_modules/satellite.js/package.json", import.meta.url));
  const metadata: unknown = JSON.parse(readFileSync(packagePath, "utf8"));
  if (!metadata || typeof metadata !== "object" || !("version" in metadata) || metadata.version !== "7.1.0") {
    throw new Error("satellite.js must match the independently qualified 7.1.0 pin");
  }
  return {
    name: "odin-satellite-javascript-entry",
    enforce: "pre",
    load(id) {
      if (id === entry) return javascriptEntrySource(readFileSync(entry, "utf8"));
      return null;
    },
  };
}
