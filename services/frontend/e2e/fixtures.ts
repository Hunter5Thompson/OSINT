import { test as base, expect, type Page } from "@playwright/test";
import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import type { LayerVisibility, SpatialApplicationV1 } from "../src/types";
import type { ReconScenesResponse } from "../src/lib/recon/types";

interface ScopeNode {
  key: string;
  kind: string;
  parent_key: string | null;
  children_available: boolean;
}
interface ScopeRecord {
  scope: ScopeNode;
  path: string[];
  presentation: {
    containment: unknown;
    preferred_lod: string | null;
    outline_lods: Record<string, Record<string, unknown>>;
    children_lods: Record<string, Record<string, unknown>>;
  };
  provenance_ref: string;
  derivation_revision: string;
}
interface Manifest {
  catalog_revision: string;
  boundary_policy: string;
  scopes: ScopeRecord[];
  assets: string[];
}
const spatialRoot = resolve("../backend/data/spatial");
const pointer = JSON.parse(readFileSync(resolve(spatialRoot, "catalog-pointer.json"), "utf8")) as {
  active_catalog_revision: string;
};
const catalogRoot = resolve(spatialRoot, "catalogs", pointer.active_catalog_revision);
const manifest = JSON.parse(readFileSync(resolve(catalogRoot, "manifest.json"), "utf8")) as Manifest;
const scopes = new Map(manifest.scopes.map(record => [record.scope.key, record]));

function renderLods(values: Record<string, Record<string, unknown>>) {
  // The public API omits feature_count on an individual boundary; manifest
  // records use null in their shared internal descriptor representation.
  return Object.fromEntries(Object.entries(values).map(([lod, descriptor]) => {
    const { feature_count, ...required } = descriptor;
    return [lod, feature_count === null ? required : descriptor];
  }));
}

export const scene: ReconScenesResponse["scenes"][number] = {
  scene_id: "browser-fixture", hf_filename: "fixture.ply", display_name: "Fixture scene",
  ply_url: "/static/recon/fixture.ply?sha=" + "a".repeat(64), ply_sha256: "a".repeat(64),
  ply_size_bytes: 100, bounds: { center_lat: 0, center_lon: 120, radius_m: 350 },
  bounds_source: "manual", default_camera: { position: [0, 0, 200], look_at: [0, 0, 0], fov_deg: 60 },
  attribution: "Synthetic browser fixture", source: "browser-test",
};

type ReconFixture = "inactive" | "error" | "available" | "malformed";
export interface FixtureState {
  recon: ReconFixture;
  contact: "none" | "aircraft" | "vessel";
  reconRequests: number;
  requests: string[];
  unexpected: string[];
  blockedExternal: string[];
}

const disabledLayers: LayerVisibility = {
  nuclearPlants: false, icbmBases: false, militaryBases: false,
  flights: false, satellites: false, earthquakes: false, vessels: false, cctv: false,
  events: false, cables: false, pipelines: false, countryBorders: false,
  cityBuildings: false, firmsHotspots: false, milAircraft: false, datacenters: false,
  refineries: false, eonet: false, gdacs: false, recon: true,
};

function application(url: URL): SpatialApplicationV1 {
  const key = url.searchParams.get("scope_key");
  return {
    schema_version: 1, requested_scope_key: key,
    catalog_revision: key ? manifest.catalog_revision : null,
    derivation_revision: key ? scopes.get(key)?.derivation_revision ?? null : null,
    boundary_policy: key ? manifest.boundary_policy : null, relation: "occurs-in",
    mode: key && key !== "world" ? "bbox_approximate" : "global",
    completeness: key && key !== "world" ? "partial" : "complete",
    included_count: 0, excluded_unlocated_count: 0, excluded_outside_count: 0,
    excluded_conflict_count: 0, excluded_stale_revision_count: 0, excluded_unsupported_count: 0,
  };
}

async function fixtures(page: Page, state: FixtureState, baseURL: string): Promise<void> {
  const origin = new URL(baseURL).origin;
  await page.context().routeWebSocket("**/*", socket => socket.close());
  await page.context().route("**/*", async route => {
    const url = new URL(route.request().url());
    if (url.origin !== origin) {
      state.blockedExternal.push(url.origin);
      await route.abort("blockedbyclient");
      return;
    }
    const path = url.pathname;
    if (!path.startsWith("/api/") && !path.startsWith("/static/recon/")) {
      await route.continue();
      return;
    }
    state.requests.push(path + url.search);
    let data: unknown;
    let status = 200;
    if (path === "/api/config") {
      data = { cesium_ion_token: "", api_version: "v1", default_layers: {
        ...disabledLayers, flights: state.contact === "aircraft", vessels: state.contact === "vessel",
      } };
    } else if (path === "/api/recon/scenes") {
      state.reconRequests++;
      status = state.recon === "error" ? 503 : 200;
      data = state.recon === "inactive"
        ? { scenes: [], availability: "disabled", reason: "not_configured" }
        : state.recon === "error" ? { detail: "configured fixture unavailable" }
        : state.recon === "malformed" ? { scenes: [{}], availability: "available" }
        : { scenes: [scene], availability: "available", reason: null };
    } else if (path === "/api/spatial/catalog") {
      data = {
        schema_version: 1, active_catalog_revision: manifest.catalog_revision,
        served_catalog_revisions: [manifest.catalog_revision], boundary_policy: manifest.boundary_policy,
        root_scope_key: "world",
        capabilities: { max_enabled_kind: "admin2", timeline_scope: "bbox_approximate", intelligence_scope: "unavailable" },
        attributions: [{ catalog_revision: manifest.catalog_revision,
          representation_note: "Tracked reference geometry; browser fixtures do not verify current boundaries.",
          sources: [{ source_id: "browser-fixture", release: "1", license_id: "fixture",
            text: "Fixture metadata; geometry from the tracked ODIN catalog" }] }],
      };
    } else if (path === "/api/spatial/scope") {
      const record = scopes.get(url.searchParams.get("scope_key") ?? "world");
      if (!record) throw new Error("Browser fixture requested an unknown scope");
      const { containment, preferred_lod, outline_lods, children_lods } = record.presentation;
      data = { schema_version: 1, catalog_revision: manifest.catalog_revision,
        boundary_policy: manifest.boundary_policy, canonicalized_from: null,
        scope: record.scope, path: record.path.map(key => scopes.get(key)?.scope),
        children: manifest.scopes.filter(item => item.scope.parent_key === record.scope.key).map(item => item.scope),
        presentation: { preferred_lod, outline_lods: renderLods(outline_lods),
          children_lods: renderLods(children_lods) }, containment, provenance_ref: record.provenance_ref,
      };
    } else if (path.startsWith("/api/spatial/assets/")) {
      const id = path.split("/").at(-1) ?? "";
      if (!manifest.assets.includes(id)) throw new Error("Browser fixture requested an unknown asset");
      const bytes = readFileSync(resolve(catalogRoot, "assets", id + ".json"));
      expect(createHash("sha256").update(bytes).digest("hex")).toBe(id);
      const contentType = route.request().headers()["accept"];
      if (contentType !== "application/vnd.odin.boundary+json;v=1"
        && contentType !== "application/vnd.odin.boundary-pack+json;v=1") {
        throw new Error("Browser fixture requires the declared boundary media type");
      }
      await route.fulfill({ status: 200, contentType, body: bytes,
        headers: { ETag: `"${id}"`, "Content-Length": String(bytes.length) } });
      return;
    } else if (path === "/api/timeline/histogram") {
      data = { t_start: url.searchParams.get("t_start"), t_end: url.searchParams.get("t_end"),
        bucket_ms: 3_600_000, buckets: [], notables: [], geo_events: [],
        total_count: 0, geo_located_count: 0, geo_truncated: false, spatial_application: application(url) };
    } else if (path === "/api/timeline/window") {
      data = { domain: url.searchParams.get("domain") ?? "events", tier: url.searchParams.get("tier") ?? "coarse",
        t_start: url.searchParams.get("t_start"), t_end: url.searchParams.get("t_end"), bbox: null,
        samples: [], total_count: 0, truncated: false, spatial_application: application(url) };
    } else if (path === "/api/graph/search") {
      data = { nodes: [{ id: "browser-location", name: "Fixture location", type: "Location",
        properties: { lat: 45, lon: 15 } }] };
    } else if (path === "/api/flights") {
      data = state.contact === "aircraft" ? [{ icao24: "e2e001", callsign: "UNKNOWN AIRCRAFT",
        latitude: 45, longitude: 15, altitude_m: null, velocity_ms: null, heading: null,
        vertical_rate: null, last_contact: null, on_ground: false, is_military: false,
        aircraft_type: null }] : [];
    } else if (path === "/api/vessels") {
      data = state.contact === "vessel" ? [{ mmsi: 205000001, name: "UNKNOWN SHIP",
        latitude: 45, longitude: 15, speed_knots: null, course: null, ship_type: 70, destination: null }] : [];
    } else if (["/api/incidents/stream", "/api/signals/stream"].includes(path)) {
      await route.fulfill({ status: 200, contentType: "text/event-stream", body: ": fixture\n\n" });
      return;
    } else if (["/api/reports", "/api/incidents", "/api/signals/latest", "/api/flights/military",
      "/api/satellites", "/api/earthquakes", "/api/hotspots", "/api/firms/hotspots",
      "/api/aircraft/tracks", "/api/eonet/events", "/api/gdacs/events"].includes(path)) {
      data = [];
    } else {
      state.unexpected.push(route.request().method() + " " + path);
      await route.fulfill({ status: 501, json: { detail: "No browser fixture for this request" } });
      return;
    }
    if (route.request().method() !== "GET") state.unexpected.push(route.request().method() + " " + path);
    const body = JSON.stringify(data);
    await route.fulfill({ status, contentType: "application/json", body,
      headers: { ETag: `"${createHash("sha256").update(body).digest("hex")}"` } });
  });
}

export const test = base.extend<{ state: FixtureState }>({
  state: async ({ page, baseURL }, use, testInfo) => {
    if (baseURL === undefined || new URL(baseURL).hostname !== "127.0.0.1") {
      throw new Error("Browser fixture requires the runner's own loopback preview");
    }
    const state: FixtureState = { recon: "inactive", contact: "none", reconRequests: 0,
      requests: [], unexpected: [], blockedExternal: [] };
    const errors: string[] = [];
    page.on("pageerror", error => errors.push(error.message));
    await fixtures(page, state, baseURL);
    await use(state);
    const rendering = await page.evaluate(() => {
      const canvas = document.querySelector<HTMLCanvasElement>(".cesium-widget canvas");
      const gl = canvas?.getContext("webgl2") ?? canvas?.getContext("webgl");
      if (!gl) return null;
      const extension = gl.getExtension("WEBGL_debug_renderer_info");
      return { renderer: String(gl.getParameter(extension ? extension.UNMASKED_RENDERER_WEBGL : gl.RENDERER)),
        vendor: String(gl.getParameter(extension ? extension.UNMASKED_VENDOR_WEBGL : gl.VENDOR)) };
    });
    await testInfo.attach("browser-contract", { contentType: "application/json", body: JSON.stringify({
      errors, ...state, rendering, limits: "No native GPU or human acceptance",
      catalogRevision: manifest.catalog_revision,
    }, null, 2) });
    expect(errors).toEqual([]);
    expect(state.unexpected).toEqual([]);
    expect(rendering?.renderer).toContain("SwiftShader");
  },
});
export { expect };
