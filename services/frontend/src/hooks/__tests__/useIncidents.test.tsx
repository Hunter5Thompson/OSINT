import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, renderHook, act, waitFor } from "@testing-library/react";

import { useIncidents } from "../useIncidents";
import { IncidentProvider } from "../../state/IncidentProvider";
import type { Incident, IncidentEnvelope } from "../../types/incident";
import * as api from "../../services/api";

class FakeES {
  static instances: FakeES[] = [];
  url: string;
  onopen: ((ev: Event) => void) | null = null;
  onerror: ((ev: Event) => void) | null = null;
  onmessage: ((ev: MessageEvent) => void) | null = null;
  listeners: Record<string, Array<(ev: MessageEvent) => void>> = {};
  constructor(url: string) {
    this.url = url;
    FakeES.instances.push(this);
  }
  addEventListener(type: string, cb: (ev: MessageEvent) => void): void {
    (this.listeners[type] ??= []).push(cb);
  }
  removeEventListener(): void {}
  close(): void {}
  emit(type: string, data: object, eventId = "1"): void {
    const ev = { data: JSON.stringify(data), lastEventId: eventId } as MessageEvent;
    if (type === "message" && this.onmessage) this.onmessage(ev);
    for (const cb of this.listeners[type] ?? []) cb(ev);
  }
}

const incidentFixture: Incident = {
  id: "inc-001",
  kind: "firms.cluster",
  title: "Sinjar ridge thermal cluster",
  severity: "high",
  coords: [36.34, 41.87],
  location: "Sinjar ridge",
  status: "open",
  trigger_ts: "2026-04-25T10:00:00Z",
  closed_ts: null,
  sources: ["firms·1"],
  layer_hints: ["firmsHotspots"],
  timeline: [{ t_offset_s: 0.0, kind: "trigger", text: "t0" }],
};

const wrapper = ({ children }: { children: React.ReactNode }) => (
  <IncidentProvider>{children}</IncidentProvider>
);

beforeEach(() => {
  FakeES.instances = [];
  (globalThis as unknown as { EventSource: typeof FakeES }).EventSource = FakeES;
  vi.spyOn(api, "getIncidents").mockResolvedValue([]);
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("IncidentProvider + useIncidents", () => {
  it("opens exactly one SSE connection regardless of consumer count", async () => {
    function Probe() {
      useIncidents();
      return null;
    }
    render(
      <IncidentProvider>
        <Probe />
        <Probe />
        <Probe />
      </IncidentProvider>,
    );
    await waitFor(() => expect(FakeES.instances.length).toBe(1));
  });

  it("hydrates from REST then transitions to live on SSE open", async () => {
    const { result } = renderHook(() => useIncidents(), { wrapper });
    await waitFor(() => expect(FakeES.instances.length).toBe(1));
    act(() => FakeES.instances[0]!.onopen?.(new Event("open")));
    await waitFor(() => expect(result.current.status).toBe("live"));
  });

  it("places incident.open into active + history", async () => {
    const { result } = renderHook(() => useIncidents(), { wrapper });
    await waitFor(() => expect(FakeES.instances.length).toBe(1));
    act(() => FakeES.instances[0]!.onopen?.(new Event("open")));

    const env: IncidentEnvelope = {
      event_id: "0001712841723482-000001",
      ts: "2026-04-25T10:00:00.000Z",
      type: "incident.open",
      payload: incidentFixture,
    };
    act(() => FakeES.instances[0]!.emit("incident.open", env, env.event_id));
    await waitFor(() => expect(result.current.active?.id).toBe("inc-001"));
    expect(result.current.history.map((i) => i.id)).toEqual(["inc-001"]);
  });

  it("removes incident from active on incident.silence", async () => {
    const { result } = renderHook(() => useIncidents(), { wrapper });
    await waitFor(() => expect(FakeES.instances.length).toBe(1));
    act(() => FakeES.instances[0]!.onopen?.(new Event("open")));

    const open: IncidentEnvelope = {
      event_id: "0001712841723482-000001",
      ts: "2026-04-25T10:00:00.000Z",
      type: "incident.open",
      payload: incidentFixture,
    };
    act(() => FakeES.instances[0]!.emit("incident.open", open, open.event_id));
    await waitFor(() => expect(result.current.active?.id).toBe("inc-001"));

    const silence: IncidentEnvelope = {
      event_id: "0001712841723482-000002",
      ts: "2026-04-25T10:01:00.000Z",
      type: "incident.silence",
      payload: { ...incidentFixture, status: "silenced" },
    };
    act(() => FakeES.instances[0]!.emit("incident.silence", silence, silence.event_id));
    await waitFor(() => expect(result.current.active).toBeNull());
  });

  it("re-hydrates from REST when a reset event arrives", async () => {
    const fresh: Incident = { ...incidentFixture, id: "inc-099" };
    const getSpy = vi.spyOn(api, "getIncidents").mockResolvedValue([fresh]);

    const { result } = renderHook(() => useIncidents(), { wrapper });
    await waitFor(() => expect(FakeES.instances.length).toBe(1));
    act(() => FakeES.instances[0]!.onopen?.(new Event("open")));
    await waitFor(() => expect(getSpy).toHaveBeenCalledTimes(1));

    act(() => FakeES.instances[0]!.emit("reset", { reason: "stale-last-event-id" }, "0"));
    await waitFor(() => expect(getSpy).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(result.current.active?.id).toBe("inc-099"));
  });

  it("falls back to a no-op result when consumed outside the provider", () => {
    const { result } = renderHook(() => useIncidents());
    expect(result.current.status).toBe("idle");
    expect(result.current.active).toBeNull();
  });

  it("hydrate selects the first OPEN incident even when newer items are promoted", async () => {
    const promoted: Incident = { ...incidentFixture, id: "inc-200", status: "promoted" };
    const open: Incident = { ...incidentFixture, id: "inc-100", status: "open" };
    vi.spyOn(api, "getIncidents").mockResolvedValue([promoted, open]);

    const { result } = renderHook(() => useIncidents(), { wrapper });
    await waitFor(() => expect(result.current.active?.id).toBe("inc-100"));
  });
});
