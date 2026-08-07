import type * as Cesium from "cesium";

import type { ResolvedPresentationInput } from "../contracts";
import {
  createCesiumSpatialScopeAdapter,
  type BoundaryAssetProvider,
  type CesiumSpatialScopeDiagnostics,
} from "./CesiumSpatialScopeAdapter";

export interface AttachedSpatialPresenter {
  present(
    input: ResolvedPresentationInput,
    stateRevision: number,
    signal: AbortSignal,
  ): Promise<void>;
  dispose(): void;
  diagnostics?(): CesiumSpatialScopeDiagnostics;
}

export interface CesiumSpatialPresentationBridgeDiagnostics {
  readonly attached: boolean;
  readonly disposed: boolean;
  readonly presenter: CesiumSpatialScopeDiagnostics | null;
  readonly waitingPresentations: number;
}

interface WaitingPresentation {
  readonly resolve: (presenter: AttachedSpatialPresenter) => void;
  readonly reject: (error: unknown) => void;
  readonly signal: AbortSignal;
  readonly onAbort: () => void;
}

export interface CesiumSpatialPresentationBridgeOptions {
  readonly assets?: BoundaryAssetProvider;
  readonly createPresenter?: (viewer: object) => AttachedSpatialPresenter;
}

function abortError(): DOMException {
  return new DOMException("The operation was aborted.", "AbortError");
}

export class CesiumSpatialPresentationBridge {
  private readonly createPresenter: (viewer: object) => AttachedSpatialPresenter;
  private readonly waiting = new Set<WaitingPresentation>();
  private viewer: object | null = null;
  private presenter: AttachedSpatialPresenter | null = null;
  private disposed = false;

  constructor(options: CesiumSpatialPresentationBridgeOptions) {
    if (options.createPresenter !== undefined) {
      this.createPresenter = options.createPresenter;
    } else {
      const assets = options.assets;
      if (assets === undefined) {
        throw new TypeError("Spatial presentation bridge requires assets or a presenter factory.");
      }
      this.createPresenter = (viewer) => createCesiumSpatialScopeAdapter(
        viewer as Cesium.Viewer,
        assets,
      );
    }
  }

  attachViewer(viewer: object): void {
    if (this.disposed) throw new Error("Spatial presentation bridge is disposed.");
    if (this.viewer === viewer && this.presenter !== null) return;
    this.presenter?.dispose();
    this.viewer = viewer;
    this.presenter = this.createPresenter(viewer);
    for (const waiter of [...this.waiting]) {
      this.finishWaiter(waiter);
      waiter.resolve(this.presenter);
    }
  }

  detachViewer(viewer: object): void {
    if (this.viewer !== viewer) return;
    this.viewer = null;
    this.presenter?.dispose();
    this.presenter = null;
  }

  async present(
    input: ResolvedPresentationInput,
    stateRevision: number,
    signal: AbortSignal,
  ): Promise<void> {
    const presenter = await this.waitForPresenter(signal);
    if (signal.aborted) throw abortError();
    await presenter.present(input, stateRevision, signal);
  }

  dispose(): void {
    if (this.disposed) return;
    this.disposed = true;
    this.viewer = null;
    this.presenter?.dispose();
    this.presenter = null;
    for (const waiter of [...this.waiting]) {
      this.finishWaiter(waiter);
      waiter.reject(abortError());
    }
  }

  diagnostics(): CesiumSpatialPresentationBridgeDiagnostics {
    return Object.freeze({
      attached: this.viewer !== null && this.presenter !== null,
      disposed: this.disposed,
      presenter: this.presenter?.diagnostics?.() ?? null,
      waitingPresentations: this.waiting.size,
    });
  }

  private waitForPresenter(signal: AbortSignal): Promise<AttachedSpatialPresenter> {
    if (signal.aborted || this.disposed) return Promise.reject(abortError());
    if (this.presenter !== null) return Promise.resolve(this.presenter);
    return new Promise<AttachedSpatialPresenter>((resolve, reject) => {
      const waiter: WaitingPresentation = {
        resolve,
        reject,
        signal,
        onAbort: () => {
          this.finishWaiter(waiter);
          reject(abortError());
        },
      };
      this.waiting.add(waiter);
      signal.addEventListener("abort", waiter.onAbort, { once: true });
    });
  }

  private finishWaiter(waiter: WaitingPresentation): void {
    this.waiting.delete(waiter);
    waiter.signal.removeEventListener("abort", waiter.onAbort);
  }
}
