import { expect, it } from "vitest";
import { layoutCapitalLabels } from "../capitalLabels";

it("separates neighboring capitals and keeps labels inside the map viewport", () => {
  const labels = layoutCapitalLabels([{ x: 400, y: 400, width: 150 }, { x: 402, y: 402, width: 150 }], 1000, 800);
  expect(labels[0]).not.toEqual(labels[1]);
  const [a, b] = labels;
  expect(Math.abs((400 + a!.y) - (402 + b!.y)) >= 40 || Math.abs((400 + a!.x) - (402 + b!.x)) >= 158).toBe(true);
  const edge = layoutCapitalLabels([{ x: 990, y: 790, width: 150 }], 1000, 800)[0]!;
  expect(990 + edge.x + 150).toBeLessThanOrEqual(990);
  expect(790 + edge.y + 36).toBeLessThanOrEqual(660);
});
