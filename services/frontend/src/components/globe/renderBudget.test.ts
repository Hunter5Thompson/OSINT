import { describe, expect, it } from "vitest";
import { RenderBudget } from "./renderBudget";

describe("actual render budget", () => {
  it("uses elapsed time rather than assuming a one-second timer", () => {
    const meter = new RenderBudget(0);
    for (let i = 0; i < 60; i++) meter.frame();
    expect(meter.sample(2000, true).fps).toBe(30);
  });
  it("degrades sustained low frame delivery and recovers slowly", () => {
    const meter = new RenderBudget(0);
    meter.sample(1000, true);
    expect(meter.sample(3000, true).degradation).toBe(1);
    for (let i = 0; i < 60; i++) meter.frame();
    meter.sample(4000, true);
    for (let i = 0; i < 300; i++) meter.frame();
    expect(meter.sample(9000, true).degradation).toBe(0);
  });
  it("does not mistake hidden or intentionally idle time for load", () => {
    const meter = new RenderBudget(0);
    meter.sample(1000, true);
    expect(meter.sample(100000, false).degradation).toBe(0);
    expect(meter.sample(101000, true).degradation).toBe(0);
    expect(meter.sample(103000, true).degradation).toBe(1);
  });
  it("keeps degradation bounded and resets the sustained-low window on recovery", () => {
    const meter = new RenderBudget(0);
    for (let t = 1000; t <= 20000; t += 1000) meter.sample(t, true);
    expect(meter.sample(21000, true).degradation).toBe(4);
    for (let i = 0; i < 60; i++) meter.frame();
    meter.sample(22000, true);
    meter.sample(23000, true);
    expect(meter.sample(24000, true).degradation).toBe(4);
  });
});
