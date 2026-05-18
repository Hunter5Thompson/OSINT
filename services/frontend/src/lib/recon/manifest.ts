import { useEffect, useState } from "react";
import type { ReconScene, ReconScenesResponse } from "./types";

interface CacheState {
  data: ReconScene[] | null;
  error: Error | null;
  inflight: Promise<void> | null;
}

const cache: CacheState = { data: null, error: null, inflight: null };

export function _resetReconManifestCache(): void {
  cache.data = null;
  cache.error = null;
  cache.inflight = null;
}

async function fetchManifest(): Promise<void> {
  try {
    const res = await fetch("/api/recon/scenes");
    if (!res.ok) {
      const body = await res.text();
      throw new Error(`recon manifest fetch failed: ${res.status} ${body}`);
    }
    const json = (await res.json()) as ReconScenesResponse;
    cache.data = json.scenes;
    cache.error = null;
  } catch (e) {
    cache.error = e instanceof Error ? e : new Error(String(e));
    cache.data = [];
  } finally {
    cache.inflight = null;
  }
}

export interface UseReconManifestResult {
  scenes: ReconScene[];
  loading: boolean;
  error: Error | null;
}

export function useReconManifest(): UseReconManifestResult {
  const [, force] = useState(0);

  useEffect(() => {
    if (cache.data !== null || cache.error !== null) return;
    if (cache.inflight === null) {
      cache.inflight = fetchManifest().then(() => force((x) => x + 1));
    } else {
      cache.inflight.then(() => force((x) => x + 1));
    }
  }, []);

  return {
    scenes: cache.data ?? [],
    loading: cache.data === null && cache.error === null,
    error: cache.error,
  };
}
