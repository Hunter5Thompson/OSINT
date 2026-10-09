import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { mkdtempSync, readFileSync, existsSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { test } from "node:test";
import { fileURLToPath } from "node:url";

const writer = fileURLToPath(new URL("./write-build-info.mjs", import.meta.url));

function run(revision) {
  const dir = mkdtempSync(join(tmpdir(), "odin-build-info-"));
  const env = { ...process.env };
  delete env.ODIN_BUILD_REVISION;
  if (revision !== undefined) env.ODIN_BUILD_REVISION = revision;
  const result = spawnSync(process.execPath, [writer], { cwd: dir, env });
  const path = join(dir, "public/build-info.json");
  return {
    result,
    exists: existsSync(path),
    info: existsSync(path) ? JSON.parse(readFileSync(path, "utf8")) : null,
    cleanup: () => rmSync(dir, { recursive: true }),
  };
}

test("a full Git revision is embedded in the frontend artifact", () => {
  const output = run("a".repeat(40));
  try {
    assert.equal(output.result.status, 0);
    assert.deepEqual(output.info, { revision: "a".repeat(40) });
  } finally { output.cleanup(); }
});

test("development builds explicitly expose an unknown revision", () => {
  for (const revision of [undefined, "unknown"]) {
    const output = run(revision);
    try {
      assert.equal(output.result.status, 0);
      assert.deepEqual(output.info, { revision: null });
    } finally { output.cleanup(); }
  }
});

test("malformed or abbreviated revisions fail the build", () => {
  for (const revision of ["", "deadbeef", "g".repeat(40), "a".repeat(40) + "extra"]) {
    const output = run(revision);
    try {
      assert.notEqual(output.result.status, 0);
      assert.match(output.result.stderr.toString(), /ODIN_BUILD_REVISION must be a full Git SHA/);
      assert.equal(output.exists, false);
    } finally { output.cleanup(); }
  }
});
