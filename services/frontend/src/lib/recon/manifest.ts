import { useEffect, useSyncExternalStore } from "react";
import { decodeReconResponse } from "./decoder";
import type { ReconScene, ReconScenesResponse } from "./types";

export interface UseReconManifestResult {
  scenes: ReconScene[];
  status: "loading" | "available" | "disabled" | "error";
  reason: ReconScenesResponse["reason"];
  loading: boolean;
  error: Error | null;
  retry: () => void;
}

function initial(): UseReconManifestResult {
  return { scenes: [], status: "loading", reason: null, loading: true, error: null, retry };
}

let state = initial();
let inflight: Promise<void> | null = null;
let generation = 0;
const listeners = new Set<() => void>();

function publish(next: UseReconManifestResult): void {
  state = next;
  listeners.forEach((listener) => listener());
}

export function _resetReconManifestCache(): void {
  generation += 1;
  inflight = null;
  publish(initial());
}

async function fetchManifest(owner: number): Promise<void> {
  try {
    const response = await fetch("/api/recon/scenes");
    if (!response.ok) throw new Error(`Recon scene request failed (${response.status})`);
    const decoded = decodeReconResponse(await response.json());
    if (owner === generation) {
      publish({ scenes: decoded.scenes, status: decoded.availability, reason: decoded.reason,
        loading: false, error: null, retry });
    }
  } catch (error) {
    if (owner === generation) {
      publish({ scenes: [], status: "error", reason: null, loading: false,
        error: error instanceof Error ? error : new Error(String(error)), retry });
    }
  } finally {
    if (owner === generation) inflight = null;
  }
}

function request(): void {
  if (inflight === null) inflight = fetchManifest(generation);
}

function retry(): void {
  if (inflight !== null) return;
  generation += 1;
  publish(initial());
  request();
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

const snapshot = (): UseReconManifestResult => state;

export function useReconManifest(): UseReconManifestResult {
  const result = useSyncExternalStore(subscribe, snapshot, snapshot);
  useEffect(() => {
    if (state.status === "loading") request();
  }, []);
  return result;
}
