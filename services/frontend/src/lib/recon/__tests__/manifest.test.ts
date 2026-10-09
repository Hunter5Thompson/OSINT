import { describe, it, expect, vi, beforeEach } from "vitest";
import { act, renderHook, waitFor } from "@testing-library/react";
import { useReconManifest, _resetReconManifestCache } from "../manifest";

const sampleScene = {
  scene_id: "jax_068",
  hf_filename: "JAX_068_final.ply",
  display_name: "Jacksonville District 068",
  ply_url: "/static/recon/JAX_068_final.ply?sha=" + "a".repeat(64),
  ply_sha256: "a".repeat(64),
  ply_size_bytes: 240164505,
  bounds: { center_lat: 30.33, center_lon: -81.65, radius_m: 350 },
  bounds_source: "spacenet_metadata",
  default_camera: { position: [0, 0, 200], look_at: [0, 0, 0], fov_deg: 60 },
  attribution: "test",
  source: "skyfall_gs_hf",
};

describe("useReconManifest", () => {
  beforeEach(() => {
    _resetReconManifestCache();
    vi.restoreAllMocks();
  });

  it("returns scenes after a successful fetch", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(
        async () =>
          new Response(JSON.stringify({ scenes: [sampleScene] }), {
            status: 200,
          }),
      ),
    );
    const { result } = renderHook(() => useReconManifest());
    await waitFor(() => expect(result.current.scenes).toHaveLength(1));
    expect(result.current.error).toBeNull();
    expect(result.current.loading).toBe(false);
  });

  it("surfaces error on 503", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(
        async () =>
          new Response(JSON.stringify({ detail: "manifest not loaded" }), {
            status: 503,
          }),
      ),
    );
    const { result } = renderHook(() => useReconManifest());
    await waitFor(() => expect(result.current.error).not.toBeNull());
    expect(result.current.scenes).toEqual([]);
  });

  it("reuses cached data on second hook invocation", async () => {
    const fetchSpy = vi.fn(
      async () =>
        new Response(JSON.stringify({ scenes: [sampleScene] }), {
          status: 200,
        }),
    );
    vi.stubGlobal("fetch", fetchSpy);
    const a = renderHook(() => useReconManifest());
    await waitFor(() => expect(a.result.current.scenes).toHaveLength(1));
    renderHook(() => useReconManifest());
    expect(fetchSpy).toHaveBeenCalledTimes(1);
  });

  it("preserves an explicitly inactive optional capability without an error", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({
      scenes: [], availability: "disabled", reason: "not_configured",
    }))));
    const { result } = renderHook(() => useReconManifest());
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current).toMatchObject({
      status: "disabled", reason: "not_configured", scenes: [], error: null,
    });
  });

  it("marks configured delivery failures as errors, never as inactive", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response("unavailable", { status: 503 })));
    const { result } = renderHook(() => useReconManifest());
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.status).toBe("error");
    expect(result.current.reason).toBeNull();
  });

  it("retries a failed request and updates every mounted consumer", async () => {
    const fetchSpy = vi.fn()
      .mockResolvedValueOnce(new Response("unavailable", { status: 503 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ scenes: [sampleScene] })));
    vi.stubGlobal("fetch", fetchSpy);
    const first = renderHook(() => useReconManifest());
    const second = renderHook(() => useReconManifest());
    await waitFor(() => expect(first.result.current.error).not.toBeNull());
    expect(second.result.current.error).not.toBeNull();
    act(() => first.result.current.retry());
    await waitFor(() => expect(first.result.current.scenes).toHaveLength(1));
    expect(second.result.current.scenes).toHaveLength(1);
    expect(second.result.current.error).toBeNull();
    expect(fetchSpy).toHaveBeenCalledTimes(2);
  });

  it.each([
    { scenes: [], availability: "disabled", reason: null },
    { scenes: [sampleScene], availability: "disabled", reason: "not_configured" },
    { scenes: [], availability: "available", reason: "operator_disabled" },
    { scenes: [{ ...sampleScene, bounds: { center_lat: 120, center_lon: 0, radius_m: 1 } }] },
    { scenes: [{ ...sampleScene, ply_url: "/static/recon/wrong.ply" }] },
    { scenes: "wrong-type" },
  ])("rejects malformed or contradictory scene responses: %j", async (payload) => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify(payload))));
    const { result } = renderHook(() => useReconManifest());
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.error).toBeInstanceOf(Error);
    expect(result.current.scenes).toEqual([]);
  });
});
