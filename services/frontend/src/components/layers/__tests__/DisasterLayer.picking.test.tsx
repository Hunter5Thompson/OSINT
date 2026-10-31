import { cleanup, render } from "@testing-library/react";
import * as Cesium from "cesium";
import { afterEach, describe, expect, it } from "vitest";
import { classifyWorldviewHit } from "../../globe/EntityClickHandler";
import { EONETLayer } from "../EONETLayer";
import { GDACSLayer } from "../GDACSLayer";

afterEach(cleanup);
describe("callback-owned disaster billboards", () => {
  it.each(["eonet", "gdacs"])("keeps %s operational while its label is decorative", (layer) => {
    const primitives = new Cesium.PrimitiveCollection();
    const viewer = { isDestroyed: () => false, canvas: document.createElement("canvas"),
      scene: { primitives, frameState: { mode: Cesium.SceneMode.SCENE3D }, pick: () => undefined },
    } as unknown as Cesium.Viewer;
    if (layer === "eonet") render(<EONETLayer viewer={viewer} visible events={[{
      id: "e", title: "test", category: "floods", status: "open", latitude: 20, longitude: 10, event_date: "2026-01-01",
    }]} />);
    else render(<GDACSLayer viewer={viewer} visible events={[{
      id: "g", event_type: "EQ", event_name: "test", alert_level: "Green", severity: 2, country: "test",
      latitude: 20, longitude: 10, from_date: "2026-01-01", to_date: "2026-01-02",
    }]} />);
    expect(classifyWorldviewHit({ primitive: (primitives.get(0) as Cesium.BillboardCollection).get(0) }, null)).toBe("operational");
    expect(classifyWorldviewHit({ primitive: (primitives.get(1) as Cesium.LabelCollection).get(0) }, null)).toBeNull();
  });
});
