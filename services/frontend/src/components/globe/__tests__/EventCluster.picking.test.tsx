import { act, render, screen } from "@testing-library/react";
import * as Cesium from "cesium";
import { afterEach, expect, it, vi } from "vitest";
import { EntityClickHandler, type CountryClickInteraction } from "../EntityClickHandler";
import { SpotlightProvider } from "../spotlight/SpotlightContext";

afterEach(() => vi.restoreAllMocks());

it("picks an aggregate as a count and zoom target without opening a fabricated single event", () => {
  const inputs = vi.spyOn(Cesium.ScreenSpaceEventHandler.prototype, "setInputAction");
  const cluster = { id: { odinKind: "operational" }, _eventClusterData: { count: 15, lat: 89, lon: 179 } };
  const camera = { flyTo: vi.fn() };
  const viewer = { isDestroyed: () => false, camera,
    scene: { canvas: document.createElement("canvas"), drillPick: vi.fn(() => [{ primitive: cluster }]) },
  } as unknown as Cesium.Viewer;
  const countryInteraction = { mode: "spatial", stateRevision: 1, onSpatialChild: vi.fn(),
    onSpatialPrefetch: vi.fn(), onBlank: vi.fn() } satisfies CountryClickInteraction;
  const onEventSelect = vi.fn();
  render(<SpotlightProvider><EntityClickHandler viewer={viewer} countryInteraction={countryInteraction}
    onEventSelect={onEventSelect} prefetchCapabilities={{ coarsePointer: false, hover: false, saveData: false }} /></SpotlightProvider>);
  const click = inputs.mock.calls.find(([, type]) => type === Cesium.ScreenSpaceEventType.LEFT_CLICK)![0] as
    (event: Cesium.ScreenSpaceEventHandler.PositionedEvent) => void;
  act(() => click({ position: new Cesium.Cartesian2(1, 2) }));
  expect(screen.getByText("15 Ereignisse · Aggregat")).toBeInTheDocument();
  expect(onEventSelect).not.toHaveBeenCalled();
  expect(countryInteraction.onSpatialChild).not.toHaveBeenCalled();
  expect(camera.flyTo).toHaveBeenCalledWith(expect.objectContaining({
    destination: Cesium.Cartesian3.fromDegrees(179, 89, 800_000),
  }));
});
