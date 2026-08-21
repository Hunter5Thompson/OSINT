import {
  HYDRATING_SPATIAL_SCOPE_SNAPSHOT,
  WORLD_SCOPE_KEY,
  SpatialScopeContractError,
  freezeSpatialScopeSnapshot,
  freezeSpatialValue,
  parseCatalogRevision,
  parseScopeLocationCandidate,
  parseScopeKeyCandidate,
  type CatalogRevision,
  type DispatchOptions,
  type OwnedSpatialScopeModule,
  type ResolvedPresentationInput,
  type ResolvedScope,
  type ScopeKey,
  type ScopeLocationEvent,
  type ScopeNavigationPort,
  type ScopeProblem,
  type SpatialCatalogPort,
  type SpatialScopeCommand,
  type SpatialScopeResult,
  type SpatialScopeSnapshot,
} from "./contracts";
import { mapSpatialCatalogProblem } from "./catalog";
import { ScopeNavigationError } from "./navigation";

export interface SpatialScopePresentationPort {
  present(
    input: ResolvedPresentationInput,
    stateRevision: number,
    signal: AbortSignal,
  ): Promise<void>;
}

export interface CreateSpatialScopeControllerOptions {
  readonly catalog: SpatialCatalogPort;
  readonly navigation: ScopeNavigationPort;
  readonly presentation?: SpatialScopePresentationPort;
  readonly createNavigationId?: () => string;
}

interface ForegroundIntent {
  readonly generation: number;
  readonly target: ScopeKey;
  readonly controller: AbortController;
  readonly detachCallerSignal: () => void;
  superseded: boolean;
  cancelledByStop: boolean;
  navigationId: string | null;
}

interface SharedResolve {
  readonly controller: AbortController;
  readonly promise: Promise<ResolvedScope>;
  consumers: number;
  settled: boolean;
}

type ForegroundResolver = (signal: AbortSignal) => Promise<ResolvedScope>;

const noPresentation: SpatialScopePresentationPort = {
  present: () => Promise.resolve(),
};

function isAbortError(error: unknown): boolean {
  return error instanceof DOMException && error.name === "AbortError";
}

function abortError(): DOMException {
  return new DOMException("The operation was aborted.", "AbortError");
}

function waitWithSignal<T>(promise: Promise<T>, signal: AbortSignal): Promise<T> {
  if (signal.aborted) return Promise.reject(abortError());
  return new Promise<T>((resolve, reject) => {
    const onAbort = () => reject(abortError());
    signal.addEventListener("abort", onAbort, { once: true });
    promise.then(resolve, reject).finally(() => signal.removeEventListener("abort", onAbort));
  });
}

function problemFromContractError(error: SpatialScopeContractError): ScopeProblem {
  return freezeSpatialValue({
    severity: "error",
    code: error.code,
    target: error.target,
    recoverable: false,
    message: error.message,
    activeCatalogRevision: null,
  });
}

function problemFromUnknown(error: unknown): ScopeProblem {
  if (error instanceof SpatialScopeContractError) return problemFromContractError(error);
  if (error instanceof ScopeNavigationError) {
    return freezeSpatialValue({
      severity: "error",
      code: error.code,
      target: error.target,
      recoverable: error.recoverable,
      message: error.message,
      activeCatalogRevision: null,
    });
  }
  return mapSpatialCatalogProblem(error);
}

function presentationProblem(target: ScopeKey, error: unknown): ScopeProblem {
  return freezeSpatialValue({
    severity: "warning",
    code: "PRESENTATION_FAILED",
    target,
    recoverable: true,
    message: error instanceof Error ? error.message : "Scope presentation failed.",
    activeCatalogRevision: null,
  });
}

class SpatialScopeController implements OwnedSpatialScopeModule {
  private readonly catalog: SpatialCatalogPort;
  private readonly navigation: ScopeNavigationPort;
  private readonly presentation: SpatialScopePresentationPort;
  private readonly createNavigationId: () => string;
  private readonly listeners = new Set<() => void>();
  private readonly sharedResolves = new Map<string, SharedResolve>();
  private readonly prefetchControllers = new Set<AbortController>();
  private readonly pendingNavigationIds = new Set<string>();
  private snapshot: SpatialScopeSnapshot = HYDRATING_SPATIAL_SCOPE_SNAPSHOT;
  private foreground: ForegroundIntent | null = null;
  private presentationController: AbortController | null = null;
  private unsubscribeNavigation: (() => void) | null = null;
  private generation = 0;
  private lifecycleGeneration = 0;
  private started = false;

  constructor(options: CreateSpatialScopeControllerOptions) {
    this.catalog = options.catalog;
    this.navigation = options.navigation;
    this.presentation = options.presentation ?? noPresentation;
    let fallbackNavigationId = 0;
    this.createNavigationId = options.createNavigationId ?? (() => {
      fallbackNavigationId += 1;
      return `odin-spatial-${fallbackNavigationId}`;
    });
  }

  getSnapshot = (): SpatialScopeSnapshot => this.snapshot;

  subscribe = (listener: () => void): (() => void) => {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  };

  start(): void {
    if (this.started) return;
    this.started = true;
    this.unsubscribeNavigation = this.navigation.subscribeLocation((event) => {
      this.onLocation(event);
    });
    const lifecycleGeneration = ++this.lifecycleGeneration;
    queueMicrotask(() => {
      if (!this.started || lifecycleGeneration !== this.lifecycleGeneration) return;
      this.hydrateCandidate(
        this.navigation.readScopeCandidate(),
        null,
        "deep-link",
      );
    });
  }

  stop(): void {
    if (!this.started && this.snapshot === HYDRATING_SPATIAL_SCOPE_SNAPSHOT) return;
    this.started = false;
    this.lifecycleGeneration += 1;
    this.generation += 1;
    if (this.foreground !== null) {
      this.foreground.cancelledByStop = true;
      this.foreground.controller.abort();
      this.foreground.detachCallerSignal();
      this.foreground = null;
    }
    this.presentationController?.abort();
    this.presentationController = null;
    for (const controller of this.prefetchControllers) controller.abort();
    this.prefetchControllers.clear();
    for (const load of this.sharedResolves.values()) load.controller.abort();
    this.sharedResolves.clear();
    this.pendingNavigationIds.clear();
    this.unsubscribeNavigation?.();
    this.unsubscribeNavigation = null;
    this.publish(HYDRATING_SPATIAL_SCOPE_SNAPSHOT);
  }

  dispatch(
    command: SpatialScopeCommand,
    options: DispatchOptions = {},
  ): Promise<SpatialScopeResult> {
    switch (command.type) {
      case "enter":
        return this.enter(command.target, options.signal);
      case "ascend":
        return this.ascend(command.cause, options.signal);
      case "hydrate":
        return this.hydrate(
          command.target,
          command.catalogRevision,
          command.cause,
          options.signal,
        );
      case "prefetch":
        return this.prefetch(command.target, command.priority, options.signal);
      case "rehydrate":
        return this.rehydrate(options.signal);
    }
  }

  private enter(target: ScopeKey, callerSignal?: AbortSignal): Promise<SpatialScopeResult> {
    const canonicalTarget = parseScopeKeyCandidate(target);
    if (this.snapshot.current?.key === canonicalTarget) {
      return Promise.resolve(this.finishUnchanged());
    }
    const revision = this.snapshot.query?.catalogRevision ?? null;
    return this.runForeground(canonicalTarget, revision, "push", callerSignal);
  }

  private ascend(
    _cause: "breadcrumb" | "keyboard",
    callerSignal?: AbortSignal,
  ): Promise<SpatialScopeResult> {
    const parent = this.snapshot.current?.parentKey ?? null;
    if (parent === null) return Promise.resolve(this.finishUnchanged());
    const revision = this.snapshot.query?.catalogRevision ?? null;
    return this.runForeground(parent, revision, "push", callerSignal);
  }

  private hydrate(
    target: ScopeKey | null,
    catalogRevision: string | null,
    cause: "browser-history" | "deep-link",
    callerSignal?: AbortSignal,
    locationNeedsCanonicalization = false,
  ): Promise<SpatialScopeResult> {
    const canonicalTarget = target === null ? WORLD_SCOPE_KEY : parseScopeKeyCandidate(target);
    const currentQuery = this.snapshot.query;
    if (
      currentQuery?.scopeKey === canonicalTarget &&
      (catalogRevision === null || catalogRevision === currentQuery.catalogRevision)
    ) {
      if (locationNeedsCanonicalization) {
        return this.replaceCommittedLocation(null);
      }
      return Promise.resolve(this.finishUnchanged());
    }
    const revision = catalogRevision === null ? null : parseCatalogRevision(catalogRevision);
    return this.runForeground(
      canonicalTarget,
      revision,
      locationNeedsCanonicalization ? "replace" : null,
      callerSignal,
      null,
      cause === "deep-link" && this.snapshot.phase === "hydrating",
      cause === "browser-history",
    );
  }

  private async prefetch(
    target: ScopeKey,
    priority: "hover" | "anticipated",
    callerSignal?: AbortSignal,
  ): Promise<SpatialScopeResult> {
    const canonicalTarget = parseScopeKeyCandidate(target);
    const revision = this.snapshot.query?.catalogRevision;
    if (revision === undefined) {
      return {
        outcome: "failed",
        problem: freezeSpatialValue({
          severity: "error",
          code: "CATALOG_UNAVAILABLE",
          target: canonicalTarget,
          recoverable: true,
          message: "Spatial scope is still hydrating.",
          activeCatalogRevision: null,
        }),
      };
    }
    const controller = new AbortController();
    const detachCallerSignal = this.forwardAbort(callerSignal, controller);
    this.prefetchControllers.add(controller);
    try {
      await this.acquireResolved(canonicalTarget, revision, controller.signal);
      if (controller.signal.aborted) throw abortError();
      await this.catalog.prefetch(canonicalTarget, revision, priority, controller.signal);
      if (controller.signal.aborted) throw abortError();
      return { outcome: "prefetched", target: canonicalTarget };
    } catch (error: unknown) {
      if (controller.signal.aborted || isAbortError(error)) return { outcome: "cancelled" };
      return { outcome: "failed", problem: problemFromUnknown(error) };
    } finally {
      detachCallerSignal();
      this.prefetchControllers.delete(controller);
    }
  }

  private rehydrate(callerSignal?: AbortSignal): Promise<SpatialScopeResult> {
    const current = this.snapshot;
    const problem = current.problem;
    if (
      current.phase === "hydrating" ||
      problem?.code !== "CATALOG_REVISION_UNAVAILABLE" ||
      problem.activeCatalogRevision === null
    ) {
      return Promise.resolve({ outcome: "unchanged", snapshot: current });
    }
    const target = current.current.key;
    const activeCatalogRevision = problem.activeCatalogRevision;
    return this.runForeground(
      target,
      activeCatalogRevision,
      "replace",
      callerSignal,
      null,
      false,
      false,
      (signal) => this.catalog.rehydrate(target, activeCatalogRevision, signal),
    );
  }

  private async runForeground(
    target: ScopeKey,
    catalogRevision: string | null,
    navigationMode: "push" | "replace" | null,
    callerSignal?: AbortSignal,
    committedProblem: ScopeProblem | null = null,
    fallbackInitialHydration = false,
    repairHistoricalFailure = false,
    resolver?: ForegroundResolver,
  ): Promise<SpatialScopeResult> {
    const intent = this.beginForeground(target, callerSignal);
    if (!intent.controller.signal.aborted) this.publishResolving(target);

    try {
      this.assertCurrent(intent);
      const resolved = await (
        resolver?.(intent.controller.signal)
        ?? this.acquireResolved(target, catalogRevision, intent.controller.signal)
      );
      this.assertCurrent(intent);

      const effectiveNavigationMode = navigationMode ?? (
        resolved.canonicalizedFrom === null ? null : "replace"
      );
      if (effectiveNavigationMode !== null) {
        const navigationId = this.createNavigationId();
        intent.navigationId = navigationId;
        this.pendingNavigationIds.add(navigationId);
        this.assertCurrent(intent);
        await waitWithSignal(this.navigation.writeScope({
          scopeKey: resolved.scope.key === WORLD_SCOPE_KEY ? null : resolved.scope.key,
          catalogRevision: resolved.query.catalogRevision,
          mode: effectiveNavigationMode,
          navigationId,
        }), intent.controller.signal);
        this.assertCurrent(intent);
        this.pendingNavigationIds.delete(navigationId);
      }

      const committed = this.commitResolved(resolved, committedProblem);
      this.finishForeground(intent);
      return { outcome: "committed", snapshot: committed };
    } catch (error: unknown) {
      if (intent.navigationId !== null) this.pendingNavigationIds.delete(intent.navigationId);
      if (intent.superseded) {
        intent.detachCallerSignal();
        return { outcome: "superseded" };
      }
      if (intent.cancelledByStop || intent.controller.signal.aborted || isAbortError(error)) {
        this.clearPending(intent);
        this.finishForeground(intent);
        return { outcome: "cancelled" };
      }
      if (!this.isCurrent(intent)) {
        intent.detachCallerSignal();
        return { outcome: "superseded" };
      }
      const problem = problemFromUnknown(error);
      if (fallbackInitialHydration && target !== WORLD_SCOPE_KEY) {
        this.finishForeground(intent);
        const fallback = await this.runForeground(
          WORLD_SCOPE_KEY,
          null,
          "replace",
          undefined,
          problem,
          false,
        );
        return fallback.outcome === "failed" ? fallback : { outcome: "failed", problem };
      }
      if (
        repairHistoricalFailure &&
        this.snapshot.phase !== "hydrating" &&
        this.snapshot.current !== null
      ) {
        const committed = this.snapshot;
        const navigationId = this.createNavigationId();
        intent.navigationId = navigationId;
        this.pendingNavigationIds.add(navigationId);
        try {
          await waitWithSignal(this.navigation.writeScope({
            scopeKey: committed.current.key === WORLD_SCOPE_KEY ? null : committed.current.key,
            catalogRevision: committed.query.catalogRevision,
            mode: "replace",
            navigationId,
          }), intent.controller.signal);
          this.assertCurrent(intent);
          this.pendingNavigationIds.delete(navigationId);
        } catch (repairError: unknown) {
          this.pendingNavigationIds.delete(navigationId);
          if (intent.superseded) {
            intent.detachCallerSignal();
            return { outcome: "superseded" };
          }
          if (intent.cancelledByStop || intent.controller.signal.aborted || isAbortError(repairError)) {
            this.clearPending(intent);
            this.finishForeground(intent);
            return { outcome: "cancelled" };
          }
          const repairProblem = problemFromUnknown(repairError);
          this.publishFailure(repairProblem);
          this.finishForeground(intent);
          return { outcome: "failed", problem: repairProblem };
        }
        this.publishFailure(problem);
        this.finishForeground(intent);
        return { outcome: "failed", problem };
      }
      this.publishFailure(problem);
      this.finishForeground(intent);
      return { outcome: "failed", problem };
    }
  }

  private beginForeground(target: ScopeKey, callerSignal?: AbortSignal): ForegroundIntent {
    if (this.foreground !== null) {
      this.foreground.superseded = true;
      this.foreground.controller.abort();
      this.foreground.detachCallerSignal();
    }
    const controller = new AbortController();
    const intent: ForegroundIntent = {
      generation: ++this.generation,
      target,
      controller,
      detachCallerSignal: this.forwardAbort(callerSignal, controller),
      superseded: false,
      cancelledByStop: false,
      navigationId: null,
    };
    this.foreground = intent;
    return intent;
  }

  private finishUnchanged(): SpatialScopeResult {
    if (this.foreground !== null) {
      this.foreground.superseded = true;
      this.foreground.controller.abort();
      this.foreground.detachCallerSignal();
      this.foreground = null;
      this.generation += 1;
      if (this.snapshot.phase === "resolving") {
        this.publish(freezeSpatialScopeSnapshot({
          ...this.snapshot,
          phase: "ready",
          pending: null,
        }));
      } else if (this.snapshot.phase === "hydrating" && this.snapshot.pending !== null) {
        this.publish(freezeSpatialScopeSnapshot({
          ...this.snapshot,
          pending: null,
        }));
      }
    }
    return { outcome: "unchanged", snapshot: this.snapshot };
  }

  private finishForeground(intent: ForegroundIntent): void {
    intent.detachCallerSignal();
    if (this.foreground === intent) this.foreground = null;
  }

  private clearPending(intent: ForegroundIntent): void {
    if (!this.isCurrent(intent)) return;
    if (this.snapshot.phase === "resolving") {
      this.publish(freezeSpatialScopeSnapshot({
        ...this.snapshot,
        phase: "ready",
        pending: null,
      }));
    } else if (this.snapshot.phase === "hydrating") {
      this.publish(freezeSpatialScopeSnapshot({
        ...this.snapshot,
        pending: null,
      }));
    }
  }

  private publishResolving(target: ScopeKey): void {
    if (this.snapshot.phase === "hydrating") {
      this.publish(freezeSpatialScopeSnapshot({
        ...this.snapshot,
        pending: target,
        problem: null,
      }));
      return;
    }
    this.publish(freezeSpatialScopeSnapshot({
      ...this.snapshot,
      phase: "resolving",
      pending: target,
      problem: null,
    }));
  }

  private publishFailure(problem: ScopeProblem): void {
    if (this.snapshot.phase === "hydrating") {
      this.publish(freezeSpatialScopeSnapshot({
        ...this.snapshot,
        pending: null,
        problem,
      }));
      return;
    }
    this.publish(freezeSpatialScopeSnapshot({
      ...this.snapshot,
      phase: "ready",
      pending: null,
      problem,
    }));
  }

  private commitResolved(
    resolved: ResolvedScope,
    committedProblem: ScopeProblem | null,
  ): SpatialScopeSnapshot {
    const stateRevision = this.snapshot.stateRevision + 1;
    this.presentationController?.abort();
    this.presentationController = null;
    const semanticOnly = resolved.presentation.mode === "semantic-only";
    const next = freezeSpatialScopeSnapshot({
      phase: "ready",
      stateRevision,
      current: resolved.scope,
      path: resolved.path,
      query: resolved.query,
      pending: null,
      problem: committedProblem ?? (semanticOnly ? resolved.presentation.problem : null),
      visual: semanticOnly
        ? {
            phase: "unavailable",
            stateRevision,
            problem: resolved.presentation.problem,
          }
        : { phase: "building", stateRevision },
    } satisfies SpatialScopeSnapshot);
    this.publish(next);

    if (resolved.presentation.mode === "boundary") {
      const controller = new AbortController();
      this.presentationController = controller;
      void this.observePresentation(
        resolved.presentation,
        stateRevision,
        controller,
      );
    }
    return next;
  }

  private async observePresentation(
    input: ResolvedPresentationInput,
    stateRevision: number,
    controller: AbortController,
  ): Promise<void> {
    try {
      await this.presentation.present(input, stateRevision, controller.signal);
      const current = this.snapshot;
      if (
        controller.signal.aborted ||
        current.phase === "hydrating" ||
        current.stateRevision !== stateRevision
      ) return;
      this.publish(freezeSpatialScopeSnapshot({
        ...current,
        visual: { phase: "ready", stateRevision },
      }));
    } catch (error: unknown) {
      const current = this.snapshot;
      if (
        controller.signal.aborted ||
        current.phase === "hydrating" ||
        current.stateRevision !== stateRevision
      ) return;
      const problem = presentationProblem(input.scopeKey, error);
      this.publish(freezeSpatialScopeSnapshot({
        ...current,
        problem,
        visual: { phase: "unavailable", stateRevision, problem },
      }));
    } finally {
      if (this.presentationController === controller) this.presentationController = null;
    }
  }

  private async acquireResolved(
    scopeKey: ScopeKey,
    catalogRevision: string | null,
    signal: AbortSignal,
  ): Promise<ResolvedScope> {
    const key = `${catalogRevision ?? "active"}\u0000${scopeKey}`;
    let load = this.sharedResolves.get(key);
    if (load === undefined) {
      const controller = new AbortController();
      load = {
        controller,
        promise: this.catalog.resolve(scopeKey, catalogRevision, controller.signal),
        consumers: 0,
        settled: false,
      };
      this.sharedResolves.set(key, load);
      const ownedLoad = load;
      ownedLoad.promise.then(
        () => this.settleSharedResolve(key, ownedLoad),
        () => this.settleSharedResolve(key, ownedLoad),
      );
    }
    load.consumers += 1;
    try {
      return await waitWithSignal(load.promise, signal);
    } finally {
      load.consumers -= 1;
      if (load.consumers === 0 && !load.settled) load.controller.abort();
    }
  }

  private settleSharedResolve(key: string, load: SharedResolve): void {
    load.settled = true;
    if (this.sharedResolves.get(key) === load) this.sharedResolves.delete(key);
  }

  private assertCurrent(intent: ForegroundIntent): void {
    if (!this.isCurrent(intent) || intent.controller.signal.aborted) throw abortError();
  }

  private isCurrent(intent: ForegroundIntent): boolean {
    return this.foreground === intent && this.generation === intent.generation;
  }

  private forwardAbort(
    source: AbortSignal | undefined,
    destination: AbortController,
  ): () => void {
    if (source === undefined) return () => undefined;
    const abort = () => destination.abort();
    if (source.aborted) destination.abort();
    else source.addEventListener("abort", abort, { once: true });
    return () => source.removeEventListener("abort", abort);
  }

  private onLocation(event: ScopeLocationEvent): void {
    if (event.navigationId !== null && this.pendingNavigationIds.delete(event.navigationId)) {
      return;
    }
    this.hydrateCandidate(
      event.scopeCandidate,
      event.catalogRevisionCandidate,
      "browser-history",
    );
  }

  private hydrateCandidate(
    candidate: string | null,
    catalogRevisionCandidate: string | null,
    cause: "browser-history" | "deep-link",
  ): void {
    let target: ScopeKey;
    let catalogRevision: CatalogRevision | null;
    let locationNeedsCanonicalization = false;
    try {
      if (candidate === null) {
        target = WORLD_SCOPE_KEY;
      } else {
        const parsed = parseScopeLocationCandidate(candidate);
        target = parsed.scopeKey;
        locationNeedsCanonicalization =
          parsed.canonicalizedFrom !== null || parsed.scopeKey === WORLD_SCOPE_KEY;
      }
      catalogRevision = catalogRevisionCandidate === null
        ? null
        : parseCatalogRevision(catalogRevisionCandidate);
    } catch (error: unknown) {
      const problem = problemFromUnknown(error);
      if (cause === "deep-link" && this.snapshot.phase === "hydrating") {
        void this.runForeground(
          WORLD_SCOPE_KEY,
          null,
          "replace",
          undefined,
          problem,
        );
      } else if (cause === "browser-history" && this.snapshot.phase !== "hydrating") {
        void this.repairCommittedLocation(problem);
      } else {
        this.publishFailure(problem);
      }
      return;
    }
    void this.hydrate(
      target,
      catalogRevision,
      cause,
      undefined,
      locationNeedsCanonicalization,
    );
  }

  private async replaceCommittedLocation(
    committedProblem: ScopeProblem | null,
  ): Promise<SpatialScopeResult> {
    if (this.snapshot.phase === "hydrating") {
      if (committedProblem !== null) this.publishFailure(committedProblem);
      return committedProblem === null
        ? { outcome: "unchanged", snapshot: this.snapshot }
        : { outcome: "failed", problem: committedProblem };
    }
    const committed = this.snapshot;
    const intent = this.beginForeground(committed.current.key);
    const navigationId = this.createNavigationId();
    intent.navigationId = navigationId;
    this.pendingNavigationIds.add(navigationId);
    try {
      await waitWithSignal(this.navigation.writeScope({
        scopeKey: committed.current.key === WORLD_SCOPE_KEY ? null : committed.current.key,
        catalogRevision: committed.query.catalogRevision,
        mode: "replace",
        navigationId,
      }), intent.controller.signal);
      this.assertCurrent(intent);
      this.pendingNavigationIds.delete(navigationId);
      if (committedProblem !== null) this.publishFailure(committedProblem);
      this.finishForeground(intent);
      return { outcome: "unchanged", snapshot: this.snapshot };
    } catch (error: unknown) {
      this.pendingNavigationIds.delete(navigationId);
      if (intent.superseded) {
        intent.detachCallerSignal();
        return { outcome: "superseded" };
      }
      if (intent.cancelledByStop || intent.controller.signal.aborted || isAbortError(error)) {
        this.clearPending(intent);
        this.finishForeground(intent);
        return { outcome: "cancelled" };
      }
      const problem = problemFromUnknown(error);
      this.publishFailure(problem);
      this.finishForeground(intent);
      return { outcome: "failed", problem };
    }
  }

  private async repairCommittedLocation(problem: ScopeProblem): Promise<void> {
    await this.replaceCommittedLocation(problem);
  }

  private publish(next: SpatialScopeSnapshot): void {
    if (next === this.snapshot) return;
    this.snapshot = next;
    for (const listener of [...this.listeners]) listener();
  }
}

export function createSpatialScopeController(
  options: CreateSpatialScopeControllerOptions,
): OwnedSpatialScopeModule {
  return new SpatialScopeController(options);
}
