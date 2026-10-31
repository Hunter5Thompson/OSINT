import { describe, expect, it } from "vitest";
import * as satellite from "satellite.js";
import reference from "../../../../tests/fixtures/satellites/reference-vectors.json";

describe("satellite.js independent WGS72 C++ qualification", () => {
  for (const sample of reference.cases) {
    for (const vector of sample.vectors) {
      it(`${sample.norad_id} ${vector.utc} preserves the catalog and TEME units`, () => {
        const parseOMM = (satellite as unknown as {
          json2satrec?: (elements: Record<string, unknown>) => satellite.SatRec;
        }).json2satrec;
        const orbit = sample.orbit;
        let record: satellite.SatRec;
        if (orbit.format === "tle") {
          record = satellite.twoline2satrec(orbit.line1!, orbit.line2!);
        } else {
          expect(parseOMM).toBeTypeOf("function");
          if (!parseOMM) throw new Error("GP-JSON propagation is unavailable");
          record = parseOMM(orbit.elements!);
        }
        expect(record.satnum).toBe(String(sample.norad_id));
        const result = satellite.propagate(record, new Date(vector.utc));
        expect(result).toBeTruthy();
        if (!result || !result.position || !result.velocity) throw new Error("No orbital solution");
        expect(result.position).toBeTypeOf("object");
        expect(result.velocity).toBeTypeOf("object");
        if (typeof result.position === "boolean" || typeof result.velocity === "boolean") {
          throw new Error("No orbital solution");
        }
        const positionError = Math.hypot(
          result.position.x - vector.position_teme_km[0]!,
          result.position.y - vector.position_teme_km[1]!,
          result.position.z - vector.position_teme_km[2]!,
        );
        const velocityError = Math.hypot(
          result.velocity.x - vector.velocity_teme_km_s[0]!,
          result.velocity.y - vector.velocity_teme_km_s[1]!,
          result.velocity.z - vector.velocity_teme_km_s[2]!,
        );
        expect(positionError).toBeLessThanOrEqual(reference.reference.position_tolerance_km);
        expect(velocityError).toBeLessThanOrEqual(reference.reference.velocity_tolerance_km_s);
      });
    }
  }
});
