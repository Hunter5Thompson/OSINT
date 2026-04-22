import { describe, it, expect } from "vitest";
import fs from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

// ESM: resolve via import.meta.url rather than __dirname (which is undefined).
const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);
const mainSrc = fs.readFileSync(
  join(__dirname, "../main.tsx"),
  "utf8",
);

describe("main.tsx StrictMode", () => {
  it("wraps RouterProvider in StrictMode", () => {
    expect(mainSrc).toMatch(/<StrictMode>[\s\S]*<RouterProvider[\s\S]*<\/StrictMode>/);
  });

  it("imports StrictMode from react", () => {
    expect(mainSrc).toMatch(/import\s+\{[^}]*StrictMode[^}]*\}\s+from\s+"react"/);
  });
});
