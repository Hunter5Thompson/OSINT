import { useCallback, useEffect, useRef, useState } from "react";
import * as Cesium from "cesium";

import { LabelArbiter, estimateLabelRect, type LabelCandidate } from "../lib/labelArbiter";
import { labelBudgetFor } from "../lib/labelBudget";
import { governorRequestRender } from "../lib/renderGovernor";

/** What a layer describes. NO screen coordinates — the hook projects. */
export interface LabelRequest {
  readonly key: string;
  readonly position: Cesium.Cartesian3;
  readonly text: string;
  readonly fontSizePx: number;
  /** The layer's own Cesium pixelOffset.y, so the collision box lands on the label. */
  readonly pixelOffsetY: number;
  readonly priority: number;
}

/**
 * Returns null when not on screen: behind globe, outside frustum, OR outside canvas.
 * worldToWindowCoordinates alone is NOT enough — it returns coords off-canvas for
 * any point in front of the camera.
 */
export type LabelProjector = (position: Cesium.Cartesian3) => { x: number; y: number } | null;

export interface LabelArbiterApi {
  submit(layerId: string, requests: readonly LabelRequest[]): void;
  remove(layerId: string): void;
  isSelected(key: string): boolean;
  readonly version: number;
}

export interface LabelArbiterViewer {
  isDestroyed(): boolean;
  readonly scene: {
    readonly canvas: { readonly clientWidth: number; readonly clientHeight: number };
  };
  readonly camera: {
    readonly positionCartographic: { readonly height: number };
    readonly moveEnd: { addEventListener(fn: () => void): () => void };
  };
}

export function useLabelArbiter(
  viewer: LabelArbiterViewer | null,
  densityPct: number,
  projector?: LabelProjector,
): LabelArbiterApi {
  const [version, setVersion] = useState(0);
  const arbiterRef = useRef(new LabelArbiter());
  const requestsRef = useRef(new Map<string, readonly LabelRequest[]>());
  const lastSelectionRef = useRef("");
  const solveScheduledRef = useRef(false);
  const densityRef = useRef(densityPct);
  const viewerRef = useRef(viewer);
  const projectorRef = useRef<LabelProjector | undefined>(projector);

  densityRef.current = densityPct;
  viewerRef.current = viewer;

  const defaultProjector = useCallback<LabelProjector>((position) => {
    const current = viewerRef.current;
    if (!current || current.isDestroyed()) return null;
    const scene = current.scene;
    // Cesium requires Scene here; the viewer type stays structural so tests
    // can fake canvas bounds without constructing a real Scene.
    const win = Cesium.SceneTransforms.worldToWindowCoordinates(scene as Cesium.Scene, position);
    if (!win) return null;
    const { clientWidth, clientHeight } = scene.canvas;
    const margin = 64;
    if (win.x < -margin || win.y < -margin) return null;
    if (win.x > clientWidth + margin || win.y > clientHeight + margin) return null;
    return { x: win.x, y: win.y };
  }, []);

  projectorRef.current = projector ?? defaultProjector;

  const solveNow = useCallback((): void => {
    const current = viewerRef.current;
    if (!current || current.isDestroyed()) return;
    const project = projectorRef.current;
    if (!project) return;

    const capacity = labelBudgetFor(current.camera.positionCartographic.height, densityRef.current);
    const candidates: LabelCandidate[] = [];
    for (const [layerId, requests] of requestsRef.current) {
      for (const request of requests) {
        const screen = project(request.position);
        if (!screen) continue;
        candidates.push({
          key: request.key,
          layerId,
          rect: estimateLabelRect(
            screen.x,
            screen.y + request.pixelOffsetY,
            request.text,
            request.fontSizePx,
          ),
          priority: request.priority,
        });
      }
    }

    const selected = arbiterRef.current.solve(candidates, { capacity, strategy: "WEIGHTED" });
    const fingerprint = [...selected].sort().join(" ");
    if (fingerprint === lastSelectionRef.current) return;
    lastSelectionRef.current = fingerprint;
    setVersion((value) => value + 1);
    governorRequestRender("label-arbiter-solve");
  }, []);

  const scheduleSolve = useCallback((): void => {
    if (solveScheduledRef.current) return;
    solveScheduledRef.current = true;
    queueMicrotask(() => {
      solveScheduledRef.current = false;
      solveNow();
    });
  }, [solveNow]);

  const submit = useCallback(
    (layerId: string, requests: readonly LabelRequest[]): void => {
      requestsRef.current.set(layerId, requests);
      scheduleSolve();
    },
    [scheduleSolve],
  );

  const remove = useCallback(
    (layerId: string): void => {
      if (!requestsRef.current.delete(layerId)) return;
      scheduleSolve();
    },
    [scheduleSolve],
  );

  const isSelected = useCallback((key: string): boolean => {
    return arbiterRef.current.isSelected(key);
  }, []);

  useEffect(() => {
    scheduleSolve();
  }, [densityPct, scheduleSolve]);

  useEffect(() => {
    if (!viewer || viewer.isDestroyed()) return;
    const unsubscribe = viewer.camera.moveEnd.addEventListener(() => {
      scheduleSolve();
    });
    return () => {
      unsubscribe();
    };
  }, [viewer, scheduleSolve]);

  useEffect(() => {
    const arbiter = arbiterRef.current;
    const requests = requestsRef.current;
    return () => {
      arbiter.clear();
      requests.clear();
      lastSelectionRef.current = "";
    };
  }, []);

  return { submit, remove, isSelected, version };
}
