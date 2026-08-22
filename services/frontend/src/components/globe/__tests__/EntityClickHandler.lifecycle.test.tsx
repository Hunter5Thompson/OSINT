import { render } from "@testing-library/react";
import type * as Cesium from "cesium";
import { describe, expect, it, vi } from "vitest";

import {
  EntityClickHandler,
  type CountryClickInteraction,
} from "../EntityClickHandler";
import { SpotlightProvider } from "../spotlight/SpotlightContext";

describe("EntityClickHandler lifecycle", () => {
  it("releases canvas listeners after the Cesium viewer is destroyed during route unmount", () => {
    const canvas = document.createElement("canvas");
    let destroyed = false;
    const viewer = {
      isDestroyed: () => destroyed,
      get scene() {
        if (destroyed) throw new TypeError("viewer.scene accessed after destroy");
        return { canvas };
      },
    } as unknown as Cesium.Viewer;
    const countryInteraction = {
      mode: "spatial",
      stateRevision: 1,
      onSpatialChild: vi.fn(),
      onSpatialPrefetch: vi.fn().mockResolvedValue(undefined),
      onBlank: vi.fn(),
    } satisfies CountryClickInteraction;

    const view = render(
      <SpotlightProvider>
        <EntityClickHandler
          viewer={viewer}
          countryInteraction={countryInteraction}
          prefetchCapabilities={{ coarsePointer: false, hover: false, saveData: false }}
        />
      </SpotlightProvider>,
    );

    destroyed = true;

    expect(() => view.unmount()).not.toThrow();
  });
});
