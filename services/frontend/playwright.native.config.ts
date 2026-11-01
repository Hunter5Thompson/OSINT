import { defineConfig } from "@playwright/test";
import base from "./playwright.config";

export default defineConfig<{ expectedRenderer: string }>({
  ...base, testMatch: /native\.(performance|lifecycle)\.perf\.ts$/, timeout: 180000,
  use: { ...base.use, expectedRenderer: "NVIDIA GeForce RTX 5090",
    headless: true, channel: "chromium", viewport: { width: 1920, height: 1080 },
    launchOptions: { args: ["--use-gl=angle", "--use-angle=gl", "--ozone-platform=x11"] },
  },
});
