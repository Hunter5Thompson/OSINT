import type { Page } from "@playwright/test";
import { test, expect, gpTime } from "./fixtures";
import { setFixedOrbitDate, resumeBrowserDate } from "./scenarioClock";

async function openWorldview(page: Page): Promise<void> {
  await page.goto("/worldview?layer=recon");
  await expect(page.locator(".cesium-widget canvas")).toHaveCount(1, { timeout: 45_000 });
  await expect(page.getByRole("button", { name: "recon", exact: true })).toBeVisible();
  await expect(page.getByTestId("chronik-spatial-status")).toHaveText("global · complete");
  await expect(page.locator(".cesium-widget-errorPanel")).toHaveCount(0);
}

test("dense synthetic flights expose rendering limits after camera and route changes", async ({ page, state }, testInfo) => {
  state.flightDensity = "dense";
  await openWorldview(page);
  await page.getByRole("button", { name: "close Layers", exact: true }).click();
  await page.getByRole("button", { name: "expand Search", exact: true }).click();
  await page.getByRole("textbox", { name: "Search entities" }).fill("Fixture location");
  await page.getByRole("button", { name: "§ Location Fixture location" }).click();
  await page.getByRole("button", { name: "close Search", exact: true }).click();
  await page.getByRole("button", { name: "expand Layers", exact: true }).click();
  const source = page.getByRole("status", { name: "Flight source and rendering" });
  await expect(source).toContainText(/(250|600|1500)\/10000 im Ausschnitt/);
  await expect(source).toContainText("durch Darstellungslimit ausgeblendet");
  await expect(source).toContainText("Keine globale Vollständigkeit");
  await page.screenshot({ path: testInfo.outputPath("synthetic-flight-density.png") });
  await page.getByRole("button", { name: "flights", exact: true }).click();
  await expect(source).toHaveCount(0);
  await page.getByRole("button", { name: "flights", exact: true }).click();
  await expect(source).toContainText(/(250|600|1500)\/10000 im Ausschnitt/);
  await page.getByRole("link", { name: /Briefing/i }).click();
  await page.getByRole("link", { name: /WorldView/i }).click();
  await expect(page.locator(".cesium-widget canvas")).toHaveCount(1, { timeout: 45_000 });
  await page.getByRole("button", { name: "expand Layers", exact: true }).click();
  await expect(page.getByRole("status", { name: "Flight source and rendering" })).toContainText("Clientabruf UTC:");
});

test("flight provider failure stays unavailable until a successful client snapshot", async ({ page, state }, testInfo) => {
  state.flightDensity = "error";
  await openWorldview(page);
  const source = page.getByRole("status", { name: "Flight source and rendering" });
  await expect(source).toContainText("Abruf fehlgeschlagen · Nicht verfügbar");
  await expect(source).not.toContainText("Keine Kontakte");
  state.flightDensity = "dense";
  await expect(source).toContainText("Clientabruf UTC:", { timeout: 20_000 });
  await expect(source).not.toContainText("Abruf fehlgeschlagen");
  await page.screenshot({ path: testInfo.outputPath("flight-provider-recovered.png") });
});

test("inactive optional Recon is off while the delivered globe remains usable", async ({ page, state }, testInfo) => {
  await openWorldview(page);
  const toggle = page.getByRole("button", { name: "recon", exact: true });
  await expect(toggle).toBeDisabled();
  await expect(toggle).toHaveAttribute("aria-pressed", "false");
  await expect(page.getByTestId("layer-toggle-recon")).toContainText("No Recon scenes configured");
  const before = state.reconRequests;
  await page.getByRole("button", { name: "Check Recon availability", exact: true }).click();
  await expect.poll(() => state.reconRequests).toBe(before + 1);
  await expect(toggle).toBeDisabled();
  const response = await page.request.get("/build-info.json");
  expect(response.status()).toBe(200);
  const build: unknown = await response.json();
  expect(build).toMatchObject({ revision: process.env.ODIN_BUILD_REVISION });
  await page.screenshot({ path: testInfo.outputPath("recon-inactive.png") });
});

for (const initial of ["error", "malformed"] as const) {
  test(`Recon ${initial} is observable and retry enables the recovered layer`, async ({ page, state }, testInfo) => {
    state.recon = initial;
    await openWorldview(page);
    const row = page.getByTestId("layer-toggle-recon");
    const toggle = page.getByRole("button", { name: "recon", exact: true });
    await expect(row).toContainText("Recon scene data unavailable");
    await expect(toggle).toBeDisabled();
    await expect(toggle).toHaveAttribute("aria-pressed", "false");
    const before = state.reconRequests;
    state.recon = "available";
    await page.getByRole("button", { name: "Retry Recon", exact: true }).click();
    await expect.poll(() => state.reconRequests).toBe(before + 1);
    await expect(toggle).toBeEnabled();
    await expect(row).not.toContainText("Recon scene data unavailable");
    // The deep link requested Recon on; recovery restores that requested state.
    await expect(toggle).toHaveAttribute("aria-pressed", "true");
    await toggle.click();
    await expect(toggle).toHaveAttribute("aria-pressed", "false");
    await toggle.click();
    await expect(toggle).toHaveAttribute("aria-pressed", "true");
    await toggle.click();
    await expect(toggle).toHaveAttribute("aria-pressed", "false");
    await page.screenshot({ path: testInfo.outputPath(`recon-${initial}-recovered.png`) });
  });
}

test("scope, time and layer controls work across a WorldView route remount", async ({ page, state }, testInfo) => {
  await openWorldview(page);
  await page.getByRole("combobox", { name: "Explore spatial scope" }).selectOption("country:UKR");
  await expect(page).toHaveURL(/scope=country%3AUKR/);
  await expect(page.getByRole("navigation", { name: "Spatial scope" })
    .getByRole("button", { name: "Ukraine", exact: true })).toHaveAttribute("aria-current", "location");
  await expect(page.getByRole("navigation", { name: "Spatial scope" })).not.toContainText("Boundary unavailable");
  await expect(page.getByTestId("chronik-spatial-status")).toHaveText("occurs-in · bbox approx · partial");
  await expect.poll(() => state.requests.some(url => url.startsWith("/api/timeline/histogram?")
    && new URL("http://fixture.test" + url).searchParams.get("scope_key") === "country:UKR")).toBe(true);
  await page.getByRole("button", { name: "7d", exact: true }).click();
  await expect(page.getByRole("button", { name: "7d", exact: true })).toHaveClass(/chronik__btn--on/);
  const initialCursor = await page.locator(".chronik__cursor").textContent();
  await page.getByRole("button", { name: "step back", exact: true }).click();
  await expect(page.locator(".chronik__cursor")).not.toHaveText(initialCursor ?? "");
  // A single step pauses the live window; reverse playback enters replay.
  await page.getByRole("button", { name: "reverse play", exact: true }).click();
  await expect(page.locator(".chronik__badge--replay")).toHaveText("▶ REPLAY");
  await page.getByRole("button", { name: "now", exact: true }).click();
  await expect(page.locator(".chronik__badge--live")).toHaveText("● LIVE");
  const flights = page.getByRole("button", { name: "flights", exact: true });
  await flights.click();
  await expect(flights).toHaveAttribute("aria-pressed", "true");
  await flights.click();
  await expect(flights).toHaveAttribute("aria-pressed", "false");
  await page.screenshot({ path: testInfo.outputPath("scope-time-layers.png") });
  await page.getByRole("link", { name: "BRIEFING", exact: true }).click();
  await expect(page).toHaveURL(/\/briefing/);
  await expect(page.locator(".cesium-widget canvas")).toHaveCount(0);
  await page.getByRole("link", { name: "WORLDVIEW", exact: true }).click();
  await expect(page).toHaveURL(/\/worldview/);
  await expect(page.locator(".cesium-widget canvas")).toHaveCount(1, { timeout: 45_000 });
  await expect(page.locator(".cesium-widget-errorPanel")).toHaveCount(0);
  // The top-level navigation links to /worldview without the old scope query.
  // Assert the current breadcrumb, not text in hidden <option> elements.
  await expect(page.getByRole("navigation", { name: "Spatial scope" })
    .getByRole("button", { name: "World", exact: true })).toHaveAttribute("aria-current", "location");
  await expect(page.getByRole("navigation", { name: "Spatial scope" })
    .getByRole("button", { name: "Ukraine", exact: true })).toHaveCount(0);
  await expect(page.getByTestId("chronik-spatial-status")).toHaveText("global · complete");
  await page.setViewportSize({ width: 1280, height: 800 });
  await page.screenshot({ path: testInfo.outputPath("route-return-1280.png") });
});

for (const contact of ["aircraft", "vessel"] as const) {
  test(`unknown ${contact} measurements stay unknown through a real globe pick`, async ({ page, state }, testInfo) => {
    state.contact = contact;
    await openWorldview(page);
    await expect(page.getByRole("button", {
      name: contact === "aircraft" ? "flights" : "vessels", exact: true,
    })).toHaveAttribute("aria-pressed", "true");
    await page.getByRole("button", { name: "close Layers", exact: true }).click();
    await page.getByRole("button", { name: "expand Search", exact: true }).click();
    await page.getByRole("textbox", { name: "Search entities" }).fill("Fixture location");
    await page.getByRole("button", { name: "§ Location Fixture location" }).click();
    await page.getByRole("button", { name: "close Search", exact: true }).click();
    const canvas = page.locator(".cesium-widget canvas");
    const box = await canvas.boundingBox();
    if (box === null) throw new Error("Globe canvas has no visible bounds");
    const label = contact === "aircraft" ? "UNKNOWN AIRCRAFT" : "UNKNOWN SHIP";
    const identity = page.getByText(contact === "aircraft" ? "icao24: e2e001" : "mmsi: 205000001", { exact: true });
    const visibleLabel = page.getByText(label, { exact: true }).filter({ visible: true }).first();
    // A click during the 1.6s camera flight cancels it and can select the
    // country below. Wait for the hollow contact to reach the canvas center,
    // then click an actually painted ring pixel. This reads a real screenshot,
    // without a Viewer hook, source rewrite or dispatched app event.
    await expect(async () => {
      if (await identity.isVisible()) return;
      const png = (await canvas.screenshot()).toString("base64");
      const pixel = await page.evaluate(async png => {
        const image = new Image();
        image.src = "data:image/png;base64," + png;
        await image.decode();
        const surface = document.createElement("canvas");
        surface.width = image.naturalWidth;
        surface.height = image.naturalHeight;
        const context = surface.getContext("2d", { willReadFrequently: true });
        if (!context) throw new Error("Screenshot pixel reader unavailable");
        context.drawImage(image, 0, 0);
        const pixels = context.getImageData(0, 0, surface.width, surface.height).data;
        const centerX = Math.floor(surface.width / 2);
        const centerY = Math.floor(surface.height / 2);
        const center = 4 * (centerY * surface.width + centerX);
        let best: { x: number; y: number; contrast: number } | null = null;
        for (let dy = -12; dy <= 12; dy++) for (let dx = -12; dx <= 12; dx++) {
          if (Math.hypot(dx, dy) < 3) continue; // Transparent ring center.
          const x = centerX + dx;
          const y = centerY + dy;
          const index = 4 * (y * surface.width + x);
          const contrast = Math.max(...[0, 1, 2].map(i => Math.abs(pixels[center + i]! - pixels[index + i]!)));
          if (contrast >= 70 && (!best || contrast > best.contrast)) best = { x, y, contrast };
        }
        return best && { x: best.x / surface.width, y: best.y / surface.height };
      }, png);
      if (pixel === null) await testInfo.attach("contact-camera", {
        contentType: "image/png", body: Buffer.from(png, "base64"),
      });
      expect(pixel, "Contact ring must be painted at the search destination").not.toBeNull();
      if (pixel === null) return;
      await canvas.click({ position: { x: pixel.x * box.width, y: pixel.y * box.height } });
      await expect(identity).toBeVisible({ timeout: 1000 });
    }).toPass({ timeout: 45_000, intervals: [500, 1000] });
    await expect(identity).toBeVisible();
    await expect(visibleLabel).toBeVisible();
    const fields = contact === "aircraft" ? ["altitude", "speed", "heading"] : ["speed", "course"];
    for (const field of fields) {
      await expect(page.getByText(`${field}: unknown`, { exact: true })).toBeVisible();
    }
    await page.screenshot({ path: testInfo.outputPath(`unknown-${contact}-picked.png`) });
  });
}

test("six-digit GP satellite is selectable in the built globe with source coverage", async ({ page, state }, testInfo) => {
  state.gp = "partial";
  await setFixedOrbitDate(page, gpTime);
  await openWorldview(page);
  await page.getByRole("button", { name: "toggle play", exact: true }).click();
  await expect(page.getByRole("button", { name: "toggle play", exact: true })).toHaveText("▶");
  const cursor = page.locator(".chronik__cursor");
  const frozenCursor = await cursor.textContent();
  // Hold simulation time through the public control; camera inertia uses Date.
  await resumeBrowserDate(page);
  // Camera input inertia needs advancing wall time even for a fixed orbit epoch.
  await expect.poll(() => page.evaluate(() => Date.now()), { timeout: 1000 })
    .toBeGreaterThan(Date.parse(gpTime));
  const source = page.getByRole("status").filter({ hasText: "Satelliten" });
  await expect(source).toContainText("1 Satelliten · 1/2 Gruppen · Teilabdeckung");
  await expect(source).toContainText(`Quellabruf UTC: ${gpTime}`);
  await page.getByRole("button", { name: "close Layers", exact: true }).click();
  await page.getByRole("button", { name: "expand Search", exact: true }).click();
  await page.getByRole("textbox", { name: "Search entities" }).fill("Fixture location");
  await page.getByRole("button", { name: "§ Location Fixture location" }).click();
  await page.getByRole("button", { name: "close Search", exact: true }).click();
  const canvas = page.locator(".cesium-widget canvas");
  const box = await canvas.boundingBox();
  if (box === null) throw new Error("Globe canvas has no visible bounds");
  // Search targets 400 km altitude; this LEO is at approximately 517.5 km.
  // Wait for the normal camera flight, then zoom above it using real controls.
  await expect(page.getByText("Fixture location", { exact: true }).first()).toBeVisible();
  // The public search flight lasts 1.6 s; let it finish before wheel input.
  await new Promise(resolve => setTimeout(resolve, 2000));
  await canvas.hover();
  await page.mouse.wheel(0, 1800);
  await page.screenshot({ path: testInfo.outputPath("gp-100651-camera.png") });
  await expect(async () => {
    await canvas.click({ position: { x: box.width / 2, y: box.height / 2 } });
    await expect(page.getByText("norad: 100651", { exact: true })).toBeVisible({ timeout: 250 });
  }).toPass({ timeout: 45_000, intervals: [500, 1000] });
  await expect(cursor).toHaveText(frozenCursor ?? "");
  await expect(page.locator(".cesium-widget-errorPanel")).toHaveCount(0);
  await expect(page.getByText("2026-205A", { exact: true }).first()).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath("gp-100651-point-orbit.png") });
  await page.getByRole("link", { name: "BRIEFING", exact: true }).click();
  await expect(canvas).toHaveCount(0);
  await page.getByRole("link", { name: "WORLDVIEW", exact: true }).click();
  await expect(page.locator(".cesium-widget canvas")).toHaveCount(1, { timeout: 45_000 });
  await expect(source).toContainText("1 Satelliten");
});

test("GP source failure is visible and a layer retry restores source data", async ({ page, state }) => {
  state.gp = "failed";
  await setFixedOrbitDate(page, gpTime);
  await openWorldview(page);
  await resumeBrowserDate(page);
  const source = page.getByRole("status").filter({ hasText: "Satelliten" });
  await expect(source).toContainText("Abruf fehlgeschlagen · Nicht verfügbar");
  const satellites = page.getByRole("button", { name: "satellites", exact: true });
  await satellites.click();
  await expect(source).toHaveCount(0);
  state.gp = "complete";
  await satellites.click();
  await expect(source).toContainText("1 Satelliten · 1/1 Gruppen");
  await expect(source).not.toContainText("Abruf fehlgeschlagen");
  expect(state.gpRequests).toBe(2);
});
