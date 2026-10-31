// Offline candidate qualification against the independently generated C++ vectors.
import { readFileSync } from "node:fs";
import { pathToFileURL } from "node:url";
import assert from "node:assert/strict";

const [modulePath, fixturePath] = process.argv.slice(2);
const satellite = await import(pathToFileURL(modulePath).href);
const fixture = JSON.parse(readFileSync(fixturePath, "utf8"));
const difference = (a, b) => Math.hypot(a.x - b[0], a.y - b[1], a.z - b[2]);
const results = [];
for (const sample of fixture.cases) {
  const orbit = sample.orbit;
  const record = orbit.format === "tle"
    ? satellite.twoline2satrec(orbit.line1, orbit.line2)
    : satellite.json2satrec(orbit.elements);
  assert.equal(record.satnum, String(sample.norad_id));
  for (const vector of sample.vectors) {
    const result = satellite.propagate(record, new Date(vector.utc));
    assert.ok(result && result.position && result.velocity);
    const positionDelta = difference(result.position, vector.position_teme_km);
    const velocityDelta = difference(result.velocity, vector.velocity_teme_km_s);
    assert.ok(positionDelta <= fixture.reference.position_tolerance_km);
    assert.ok(velocityDelta <= fixture.reference.velocity_tolerance_km_s);
    results.push({ norad_id: sample.norad_id, utc: vector.utc,
      position_delta_km: positionDelta, velocity_delta_km_s: velocityDelta });
  }
}
process.stdout.write(JSON.stringify({ time_zone: process.env.TZ, node: process.version,
  reference: fixture.reference, results,
  max_position_delta_km: Math.max(...results.map(row => row.position_delta_km)),
  max_velocity_delta_km_s: Math.max(...results.map(row => row.velocity_delta_km_s)) }, null, 2) + "\n");
