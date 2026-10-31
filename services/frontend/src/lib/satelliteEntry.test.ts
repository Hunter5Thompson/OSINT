import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import { javascriptEntrySource } from "../../scripts/satellite-javascript-entry";

describe("pinned JavaScript satellite build boundary", () => {
  it("excludes only the unused optional WASM barrel without touching math exports", () => {
    const source = readFileSync(resolve("node_modules/satellite.js/dist/index.js"), "utf8");
    const result = javascriptEntrySource(source);
    expect(result).toBe(source.replace("export * from './wasm/index.js';", ""));
    expect(result).toContain("twoline2satrec, json2satrec");
    expect(result).toContain("eciToGeodetic");
    expect(result).not.toContain("wasm/index.js");
  });

  it.each(["unexpected export shape", "export * from './wasm/index.js';\nexport * from './wasm/index.js';"])(
    "fails closed when the upstream entry changes: %s", (source) => {
      expect(() => javascriptEntrySource(source)).toThrow("requalify");
    },
  );
});
