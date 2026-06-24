import { Profiler, useEffect } from "react";
import { act, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import * as Cesium from "cesium";

import { CapitalPulse } from "./CapitalPulse";
import { SpotlightProvider, useSpotlight } from "./SpotlightContext";

function FocusCountry() {
  const { dispatch } = useSpotlight();

  useEffect(() => {
    dispatch({
      type: "set",
      target: {
        kind: "country",
        trigger: "country",
        m49: "300",
        iso3: "GRC",
        name: "Greece",
        polygon: {
          type: "Polygon",
          coordinates: [[[20, 35], [25, 35], [25, 40], [20, 35]]],
        },
        capital: { name: "Athens", coords: { lon: 23.73, lat: 37.98 } },
      },
    });
  }, [dispatch]);

  return null;
}

describe("CapitalPulse", () => {
  it("updates per-frame screen position without a React commit", async () => {
    let preUpdate: (() => void) | null = null;
    const removePreUpdate = vi.fn();
    const viewer = {
      isDestroyed: () => false,
      scene: {
        preUpdate: {
          addEventListener: vi.fn((listener: () => void) => {
            preUpdate = listener;
            return removePreUpdate;
          }),
        },
      },
    } as unknown as Cesium.Viewer;
    let x = 100;
    vi.spyOn(Cesium.SceneTransforms, "worldToWindowCoordinates").mockImplementation(() => {
      x += 1;
      return new Cesium.Cartesian2(x, 200);
    });
    let commits = 0;

    render(
      <Profiler id="capital" onRender={() => { commits += 1; }}>
        <SpotlightProvider>
          <FocusCountry />
          <CapitalPulse viewer={viewer} />
        </SpotlightProvider>
      </Profiler>,
    );

    await screen.findByText("Athens");
    commits = 0;

    await act(async () => {
      preUpdate?.();
      preUpdate?.();
      await Promise.resolve();
    });

    expect(commits).toBe(0);
  });
});
