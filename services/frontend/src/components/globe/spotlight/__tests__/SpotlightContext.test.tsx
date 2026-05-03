import { describe, it, expect } from "vitest";
import { render, fireEvent } from "@testing-library/react";
import { spotlightReducer, type FocusTarget, type SpotlightAction, SpotlightProvider, useSpotlight } from "../SpotlightContext";

const idle: FocusTarget = null;

const samplePin: SpotlightAction = {
  type: "set",
  target: {
    kind: "circle",
    trigger: "pin",
    center: { lon: 41.87, lat: 36.34 },
    radius: 1,
    altitude: 312_000,
    label: "Sinjar Ridge",
    sourcePin: { layer: "events", entityId: "evt-44" },
  },
};

const sampleCountry: SpotlightAction = {
  type: "set",
  target: {
    kind: "country",
    trigger: "country",
    m49: "300",
    iso3: "GRC",
    polygon: { type: "Polygon", coordinates: [[[20, 40], [25, 40], [25, 38], [20, 38], [20, 40]]] },
    name: "Greece",
    capital: { name: "Athens", coords: { lon: 23.7275, lat: 37.9838 } },
  },
};

describe("spotlightReducer", () => {
  it("idle → focused (pin)", () => {
    const next = spotlightReducer(idle, samplePin);
    expect(next?.kind).toBe("circle");
    expect(next?.trigger).toBe("pin");
  });

  it("idle → focused (country)", () => {
    const next = spotlightReducer(idle, sampleCountry);
    expect(next?.kind).toBe("country");
    expect(next && "iso3" in next ? next.iso3 : null).toBe("GRC");
  });

  it("country can have null iso3 (graceful fallback)", () => {
    const fallback: SpotlightAction = {
      type: "set",
      target: {
        kind: "country", trigger: "country", m49: "732", iso3: null,
        polygon: { type: "Polygon", coordinates: [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]] },
        name: "W. Sahara", capital: null,
      },
    };
    const next = spotlightReducer(idle, fallback);
    expect(next && "iso3" in next ? next.iso3 : "x").toBeNull();
  });

  it("last-writer-wins: pin → country replaces", () => {
    const afterPin = spotlightReducer(idle, samplePin);
    const afterCountry = spotlightReducer(afterPin, sampleCountry);
    expect(afterCountry?.kind).toBe("country");
  });

  it("reset → idle", () => {
    const afterPin = spotlightReducer(idle, samplePin);
    const next = spotlightReducer(afterPin, { type: "reset" });
    expect(next).toBeNull();
  });
});

function Probe() {
  const { focusTarget, dispatch } = useSpotlight();
  return (
    <>
      <button onClick={() => dispatch({ type: "set", target: { kind: "circle", trigger: "pin", center: { lon: 0, lat: 0 }, radius: 1, altitude: 0, label: "x" } })}>set</button>
      <span data-testid="state">{focusTarget?.kind ?? "idle"}</span>
    </>
  );
}

it("ESC resets focusTarget to null", async () => {
  const { getByText, getByTestId } = render(<SpotlightProvider><Probe /></SpotlightProvider>);
  fireEvent.click(getByText("set"));
  expect(getByTestId("state").textContent).toBe("circle");
  fireEvent.keyDown(window, { key: "Escape" });
  expect(getByTestId("state").textContent).toBe("idle");
});
