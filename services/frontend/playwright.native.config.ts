import { defineConfig } from "@playwright/test";
import base from "./playwright.config";
import nativeProfile from "./scripts/native-browser-profile.json" with { type: "json" };

export default defineConfig<{ expectedRenderer: string; expectedBrowserVersion: string; requireSpatialCatalog: boolean }>({
  ...base, testMatch: /native\.(performance|lifecycle|recovery|workers)\.perf\.ts$/, timeout: 180000,
  use: { ...base.use, expectedRenderer: "Vulkan 1.4.329 (NVIDIA NVIDIA GeForce RTX 5090",
    expectedBrowserVersion: nativeProfile.chromiumVersion,
    requireSpatialCatalog: true,
    actionTimeout: 15000, navigationTimeout: 30000,
    headless: true, channel: "chromium", viewport: { width: 1920, height: 1080 },
    launchOptions: { args: nativeProfile.args },
  },
});
