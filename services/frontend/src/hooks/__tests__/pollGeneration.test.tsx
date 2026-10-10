import { act, cleanup, renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import gp from "../../../../../tests/fixtures/satellites/celestrak-100651.json";
import { useEarthquakes } from "../useEarthquakes";
import { useFIRMSHotspots } from "../useFIRMSHotspots";
import { useAircraftTracks } from "../useAircraftTracks";
import { useSatellites } from "../useSatellites";
import { useCables } from "../useCables";
import { useEONETEvents } from "../useEONETEvents";
import { useGDACSEvents } from "../useGDACSEvents";

interface Props { enabled: boolean; sinceHours: number }
interface FeedCase {
  name: string;
  interval: number;
  parameter: boolean;
  useHook(p: Props): { items: readonly unknown[]; loading: boolean; lastUpdate: Date | null };
}
const cases: FeedCase[] = [
  { name: "earthquakes", interval: 300_000, parameter: false, useHook: (p: Props) => {
    const h = useEarthquakes(p.enabled); return { ...h, items: h.earthquakes }; } },
  { name: "firms", interval: 60_000, parameter: true, useHook: (p: Props) => {
    const h = useFIRMSHotspots(p.enabled, p.sinceHours); return { ...h, items: h.hotspots }; } },
  { name: "tracks", interval: 30_000, parameter: true, useHook: (p: Props) => {
    const h = useAircraftTracks(p.enabled, p.sinceHours); return { ...h, items: h.tracks }; } },
  { name: "satellites", interval: 3_600_000, parameter: false, useHook: (p: Props) => {
    const h = useSatellites(p.enabled); return { ...h, items: h.satellites }; } },
  { name: "cables", interval: 3_600_000, parameter: false, useHook: (p: Props) => {
    const h = useCables(p.enabled); return { ...h, items: h.cables }; } },
  { name: "eonet", interval: 120_000, parameter: true, useHook: (p: Props) => {
    const h = useEONETEvents(p.enabled, p.sinceHours); return { ...h, items: h.events }; } },
  { name: "gdacs", interval: 120_000, parameter: true, useHook: (p: Props) => {
    const h = useGDACSEvents(p.enabled, p.sinceHours); return { ...h, items: h.events }; } },
];

function body(feed: string, name: string) {
  if (feed === "cables") return { cables: [{ id: name }], landing_points: [{ id: name }], source: name };
  if (feed !== "satellites") return [{ id: name }];
  return {
    schema_version: 1, fetched_at: "2026-10-10T00:00:00Z",
    satellites: [{ norad_id: 100651, name, category: "active", operator_country: null, satellite_type: "unknown",
      inclination_deg: gp.INCLINATION, period_min: 1440 / gp.MEAN_MOTION,
      orbit: { format: "omm", elements: { ...gp, EPOCH: gp.EPOCH + "Z", CENTER_NAME: "EARTH",
        REF_FRAME: "TEME", TIME_SYSTEM: "UTC", MEAN_ELEMENT_THEORY: "SGP4" } } }],
    coverage: { completeness: "complete", groups: [{ group: "active", status: "ok", accepted_records: 1,
      rejected_invalid: 0, rejected_unsupported: 0, rejections: [], failure_code: null }] },
  };
}

function requests() {
  const pending: { resolve: (r: Response) => void; reject: (e: Error) => void; signal: AbortSignal | null | undefined }[] = [];
  vi.stubGlobal("fetch", vi.fn<typeof fetch>().mockImplementation((_url, init) =>
    new Promise<Response>((resolve, reject) => pending.push({ resolve, reject, signal: init?.signal }))));
  return pending;
}
afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.useRealTimers(); });

describe.each(cases)("$name request generation", (feed) => {
  const props = { enabled: true, sinceHours: 24 };
  const expected = (name: string) => feed.name === "satellites" ? { name } : { id: name };

  it("keeps B when A resolves after the next poll", async () => {
    vi.useFakeTimers();
    const pending = requests();
    const { result } = renderHook(feed.useHook, { initialProps: props });
    act(() => vi.advanceTimersByTime(feed.interval));
    await act(async () => pending[1]!.resolve(Response.json(body(feed.name, "B"))));
    const updated = result.current.lastUpdate;
    await act(async () => pending[0]!.resolve(Response.json(body(feed.name, "A"))));
    expect(result.current.items[0]).toMatchObject(expected("B"));
    expect(result.current.lastUpdate).toEqual(updated);
    expect(result.current.loading).toBe(false);
    expect(pending[0]!.signal?.aborted).toBe(true);
  });

  it("an old error/finally cannot end the newer loading request", async () => {
    vi.useFakeTimers();
    const pending = requests();
    const { result } = renderHook(feed.useHook, { initialProps: props });
    act(() => vi.advanceTimersByTime(feed.interval));
    await act(async () => pending[0]!.reject(new Error("old failure")));
    expect(result.current.loading).toBe(true);
    await act(async () => pending[1]!.resolve(Response.json(body(feed.name, "B"))));
    expect(result.current.items[0]).toMatchObject(expected("B"));
    expect(result.current.loading).toBe(false);
  });

  it("disable clears and rejects late responses", async () => {
    const pending = requests();
    const { result, rerender } = renderHook(feed.useHook, { initialProps: props });
    rerender({ ...props, enabled: false });
    await act(async () => pending[0]!.resolve(Response.json(body(feed.name, "A"))));
    expect(result.current.items).toEqual([]);
    expect(result.current.loading).toBe(false);
    expect(pending[0]!.signal?.aborted).toBe(true);
  });

  it("an old failure after B succeeds cannot change its data or update time", async () => {
    vi.useFakeTimers();
    const pending = requests();
    const { result } = renderHook(feed.useHook, { initialProps: props });
    act(() => vi.advanceTimersByTime(feed.interval));
    await act(async () => pending[1]!.resolve(Response.json(body(feed.name, "B"))));
    const before = result.current;
    await act(async () => pending[0]!.reject(new Error("old failure")));
    expect(result.current.items).toEqual(before.items);
    expect(result.current.lastUpdate).toEqual(before.lastUpdate);
    expect(result.current.loading).toBe(false);
    expect(result.current).not.toHaveProperty("error", "old failure");
  });

  it("disable/enable invalidates a resolved old generation", async () => {
    const pending = requests();
    const { result, rerender } = renderHook(feed.useHook, { initialProps: props });
    rerender({ ...props, enabled: false });
    rerender(props);
    await act(async () => pending[1]!.resolve(Response.json(body(feed.name, "B"))));
    await act(async () => pending[0]!.resolve(Response.json(body(feed.name, "A"))));
    expect(result.current.items[0]).toMatchObject(expected("B"));
  });

  it("unmount aborts and late work cannot publish", async () => {
    const pending = requests();
    const { unmount } = renderHook(feed.useHook, { initialProps: props });
    unmount();
    expect(pending[0]!.signal?.aborted).toBe(true);
    await act(async () => pending[0]!.resolve(Response.json(body(feed.name, "A"))));
  });

  if (feed.parameter) it("parameter change keeps only the matching response", async () => {
    const pending = requests();
    const { result, rerender } = renderHook(feed.useHook, { initialProps: props });
    rerender({ ...props, sinceHours: 48 });
    await act(async () => pending[1]!.resolve(Response.json(body(feed.name, "B"))));
    await act(async () => pending[0]!.resolve(Response.json(body(feed.name, "A"))));
    expect(result.current.items[0]).toMatchObject(expected("B"));
    expect(pending[0]!.signal?.aborted).toBe(true);
  });
});
