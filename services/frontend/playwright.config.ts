import { defineConfig } from "@playwright/test";
import { resolve } from "node:path";

const port = Number(process.env.ODIN_BROWSER_PORT ?? "15174");
if (!Number.isInteger(port) || port < 1024 || port > 65535) {
  throw new Error("ODIN_BROWSER_PORT must be an unprivileged TCP port");
}
const artifacts = resolve(process.env.ODIN_BROWSER_ARTIFACTS ?? "test-results");

export default defineConfig({
  testDir: "./e2e",
  outputDir: artifacts,
  fullyParallel: false,
  workers: 1,
  retries: 0,
  forbidOnly: Boolean(process.env.CI),
  // SwiftShader readbacks and context setup take tens of seconds on a two-core
  // runner. Keep the DOM assertions strict while budgeting the complete case.
  timeout: 180_000,
  globalTimeout: 1_800_000,
  expect: { timeout: 15_000 },
  reporter: [["list"], ["json", { outputFile: resolve(artifacts, "results.json") }]],
  use: {
    baseURL: `http://127.0.0.1:${port}`,
    browserName: "chromium",
    viewport: { width: 1440, height: 1000 },
    serviceWorkers: "block",
    trace: "on",
    screenshot: "only-on-failure",
    launchOptions: {
      args: ["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader"],
    },
  },
  webServer: {
    command: `npm run preview -- --host 127.0.0.1 --port ${port} --strictPort`,
    url: `http://127.0.0.1:${port}`,
    reuseExistingServer: false,
    timeout: 30_000,
  },
});
