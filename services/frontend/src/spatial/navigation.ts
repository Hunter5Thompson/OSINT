import {
  freezeSpatialValue,
  parseCatalogRevision,
  parseScopeKeyCandidate,
  type ScopeKey,
  type ScopeLocationEvent,
  type ScopeNavigationPort,
  type ScopeNavigationWrite,
} from "./contracts";

export interface ScopeNavigationClock {
  setTimeout(callback: () => void, delayMs: number): number;
  clearTimeout(id: number): void;
}

export interface RouterLocationSnapshot {
  readonly pathname: string;
  readonly search: string;
  readonly hash: string;
  readonly state: unknown;
}

export interface RouterNavigationRequest extends RouterLocationSnapshot {
  readonly replace: boolean;
}

export interface ScopeNavigationErrorInit {
  readonly target?: string | null;
  readonly message: string;
  readonly cause?: unknown;
}

export class ScopeNavigationError extends Error {
  readonly code = "URL_SYNC_FAILED" as const;
  readonly target: string | null;
  readonly recoverable = true as const;

  constructor(init: ScopeNavigationErrorInit) {
    super(init.message, { cause: init.cause });
    this.name = "ScopeNavigationError";
    this.target = init.target ?? null;
  }
}

const browserClock: ScopeNavigationClock = {
  setTimeout: (callback, delayMs) => window.setTimeout(callback, delayMs),
  clearTimeout: (id) => window.clearTimeout(id),
};

const NAVIGATION_ID = /^[A-Za-z0-9._:-]{1,128}$/;
const URL_SYNC_TIMEOUT_MS = 2_000;
const MAX_STALE_NAVIGATION_IDS = 100;

function abortError(): DOMException {
  return new DOMException("The operation was aborted.", "AbortError");
}

function isStateRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function readLocationEvent(location: RouterLocationSnapshot): ScopeLocationEvent {
  const search = location.search.startsWith("?") ? location.search.slice(1) : location.search;
  const candidates = new URLSearchParams(search).getAll("scope");
  const scopeCandidate = candidates.length === 0
    ? null
    : candidates.length === 1
      ? candidates[0] ?? ""
      : "";
  const state = isStateRecord(location.state) ? location.state : null;
  const revisionValue = state?.odinSpatialCatalogRevision;
  let catalogRevisionCandidate: string | null = null;
  if (typeof revisionValue === "string") {
    try {
      catalogRevisionCandidate = parseCatalogRevision(revisionValue);
    } catch {
      catalogRevisionCandidate = null;
    }
  }
  const navigationValue = state?.odinSpatialNavigationId;
  const navigationId = typeof navigationValue === "string" && NAVIGATION_ID.test(navigationValue)
    ? navigationValue
    : null;
  return freezeSpatialValue({
    scopeCandidate,
    catalogRevisionCandidate,
    navigationId,
  });
}

function normalizeLocation(location: RouterLocationSnapshot): RouterLocationSnapshot {
  return {
    pathname: location.pathname,
    search: location.search,
    hash: location.hash,
    state: location.state,
  };
}

function mergeState(
  state: unknown,
  navigationId: string,
  catalogRevision: string,
): Record<string, unknown> {
  const foreign = isStateRecord(state)
    ? state
    : state === null || state === undefined
      ? {}
      : { odinSpatialForeignState: state };
  return {
    ...foreign,
    odinSpatialNavigationId: navigationId,
    odinSpatialCatalogRevision: catalogRevision,
  };
}

function buildRequest(
  location: RouterLocationSnapshot,
  write: ScopeNavigationWrite,
  replace = write.mode === "replace",
): RouterNavigationRequest {
  const search = location.search.startsWith("?") ? location.search.slice(1) : location.search;
  const parameters = new URLSearchParams(search);
  if (write.scopeKey === null) parameters.delete("scope");
  else parameters.set("scope", write.scopeKey);
  const serialized = parameters.toString();
  return {
    pathname: location.pathname,
    search: serialized === "" ? "" : `?${serialized}`,
    hash: location.hash,
    state: mergeState(location.state, write.navigationId, write.catalogRevision),
    replace,
  };
}

interface PendingRouterWrite {
  readonly write: ScopeNavigationWrite;
  readonly resolve: () => void;
  readonly reject: (error: unknown) => void;
  timer: number | null;
  fallback: ScopeNavigationWrite | null;
}

export interface RouterScopeNavigationOptions {
  readonly initialLocation: RouterLocationSnapshot;
  readonly navigate: (request: RouterNavigationRequest) => void | Promise<void>;
  readonly clock?: ScopeNavigationClock;
  readonly syncTimeoutMs?: number;
}

export class RouterScopeNavigation implements ScopeNavigationPort {
  private readonly navigate: RouterScopeNavigationOptions["navigate"];
  private readonly clock: ScopeNavigationClock;
  private readonly syncTimeoutMs: number;
  private readonly listeners = new Set<(event: ScopeLocationEvent) => void>();
  private readonly queue: PendingRouterWrite[] = [];
  private readonly staleNavigationIds = new Set<string>();
  private readonly repairNavigationIds = new Set<string>();
  private location: RouterLocationSnapshot;
  private active: PendingRouterWrite | null = null;
  private latestDesired: ScopeNavigationWrite | null = null;
  private latestCommitted: ScopeNavigationWrite | null = null;
  private disposed = false;

  constructor(options: RouterScopeNavigationOptions) {
    this.location = normalizeLocation(options.initialLocation);
    this.navigate = options.navigate;
    this.clock = options.clock ?? browserClock;
    this.syncTimeoutMs = options.syncTimeoutMs ?? URL_SYNC_TIMEOUT_MS;
  }

  readScopeCandidate(): string | null {
    return readLocationEvent(this.location).scopeCandidate;
  }

  writeScope(write: ScopeNavigationWrite): Promise<void> {
    if (this.disposed) return Promise.reject(abortError());
    const canonical = this.validateWrite(write);
    this.latestDesired = canonical;
    return new Promise<void>((resolve, reject) => {
      this.queue.push({
        write: canonical,
        resolve,
        reject,
        timer: null,
        fallback: null,
      });
      this.processQueue();
    });
  }

  subscribeLocation(listener: (event: ScopeLocationEvent) => void): () => void {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  acceptLocation(location: RouterLocationSnapshot): void {
    this.location = normalizeLocation(location);
    const event = readLocationEvent(this.location);

    if (this.active !== null && event.navigationId === this.active.write.navigationId) {
      const expectedScope = this.active.write.scopeKey;
      if (
        event.scopeCandidate === expectedScope &&
        event.catalogRevisionCandidate === this.active.write.catalogRevision
      ) {
        this.completeActive(event);
      }
      return;
    }

    if (event.navigationId !== null && this.staleNavigationIds.delete(event.navigationId)) {
      this.repairLatestLocation();
      return;
    }
    if (event.navigationId !== null && this.repairNavigationIds.delete(event.navigationId)) {
      return;
    }

    for (const listener of [...this.listeners]) listener(event);
  }

  cancelPending(): void {
    const cancellation = abortError();
    if (this.active !== null) {
      if (this.active.timer !== null) this.clock.clearTimeout(this.active.timer);
      this.active.reject(cancellation);
      this.active = null;
    }
    this.queue.splice(0).forEach((pending) => pending.reject(cancellation));
    this.latestDesired = this.latestCommitted;
  }

  dispose(): void {
    if (this.disposed) return;
    this.cancelPending();
    this.disposed = true;
    this.listeners.clear();
    this.staleNavigationIds.clear();
    this.repairNavigationIds.clear();
  }

  private validateWrite(write: ScopeNavigationWrite): ScopeNavigationWrite {
    if (!NAVIGATION_ID.test(write.navigationId)) {
      throw new ScopeNavigationError({
        target: write.scopeKey,
        message: "Navigation ID is invalid.",
      });
    }
    const revision = parseCatalogRevision(write.catalogRevision);
    let scopeKey: ScopeKey | null = null;
    if (write.scopeKey !== null) {
      scopeKey = parseScopeKeyCandidate(write.scopeKey);
      if (scopeKey !== write.scopeKey) {
        throw new ScopeNavigationError({
          target: write.scopeKey,
          message: "Navigation scope must already be canonical.",
        });
      }
    }
    return freezeSpatialValue({ ...write, scopeKey, catalogRevision: revision });
  }

  private processQueue(): void {
    if (this.disposed || this.active !== null) return;
    const pending = this.queue.shift();
    if (pending === undefined) return;
    pending.fallback = this.latestCommitted ?? this.fallbackForCurrentLocation(pending.write);
    this.active = pending;
    pending.timer = this.clock.setTimeout(() => {
      this.failActive(new ScopeNavigationError({
        target: pending.write.scopeKey,
        message: "Router did not confirm the spatial URL within two seconds.",
      }), true);
    }, this.syncTimeoutMs);
    try {
      const result = this.navigate(buildRequest(this.location, pending.write));
      if (result instanceof Promise) {
        void result.catch((error: unknown) => {
          if (this.active === pending) {
            this.failActive(new ScopeNavigationError({
              target: pending.write.scopeKey,
              message: "Router navigation failed before its location echo.",
              cause: error,
            }), false);
          }
        });
      }
    } catch (error: unknown) {
      this.failActive(new ScopeNavigationError({
        target: pending.write.scopeKey,
        message: "Router navigation failed before its location echo.",
        cause: error,
      }), false);
    }
  }

  private completeActive(event: ScopeLocationEvent): void {
    const completed = this.active;
    if (completed === null) return;
    if (completed.timer !== null) this.clock.clearTimeout(completed.timer);
    this.active = null;
    this.latestCommitted = completed.write;
    for (const listener of [...this.listeners]) listener(event);
    completed.resolve();
    this.processQueue();
  }

  private failActive(error: ScopeNavigationError, mayEchoLate: boolean): void {
    const failed = this.active;
    if (failed === null) return;
    if (failed.timer !== null) this.clock.clearTimeout(failed.timer);
    this.active = null;
    if (mayEchoLate) this.rememberStaleNavigationId(failed.write.navigationId);
    if (this.latestDesired?.navigationId === failed.write.navigationId) {
      this.latestDesired = failed.fallback;
    }
    failed.reject(error);
    this.processQueue();
  }

  private fallbackForCurrentLocation(write: ScopeNavigationWrite): ScopeNavigationWrite | null {
    const event = readLocationEvent(this.location);
    let scopeKey: ScopeKey | null;
    try {
      scopeKey = event.scopeCandidate === null
        ? null
        : parseScopeKeyCandidate(event.scopeCandidate);
    } catch {
      return null;
    }
    return freezeSpatialValue({
      scopeKey,
      catalogRevision: write.catalogRevision,
      mode: "replace",
      navigationId: `${write.navigationId}:rollback`.slice(0, 128),
    });
  }

  private rememberStaleNavigationId(navigationId: string): void {
    this.staleNavigationIds.add(navigationId);
    while (this.staleNavigationIds.size > MAX_STALE_NAVIGATION_IDS) {
      const oldest = this.staleNavigationIds.values().next().value;
      if (typeof oldest !== "string") break;
      this.staleNavigationIds.delete(oldest);
    }
  }

  private repairLatestLocation(): void {
    const desired = this.active?.write ?? this.latestDesired ?? this.latestCommitted;
    if (desired === null) return;
    if (this.active === null) this.repairNavigationIds.add(desired.navigationId);
    try {
      const result = this.navigate(buildRequest(this.location, desired, true));
      if (result instanceof Promise) {
        void result.catch(() => this.repairNavigationIds.delete(desired.navigationId));
      }
    } catch {
      this.repairNavigationIds.delete(desired.navigationId);
    }
  }
}

export interface MemoryScopeNavigationOptions {
  readonly initialScopeCandidate?: string | null;
  readonly initialCatalogRevisionCandidate?: string | null;
  readonly clock?: ScopeNavigationClock;
  readonly echoDelayMs?: number;
}

export class MemoryScopeNavigation implements ScopeNavigationPort {
  private readonly clock: ScopeNavigationClock;
  private readonly echoDelayMs: number;
  private readonly listeners = new Set<(event: ScopeLocationEvent) => void>();
  private readonly writeLog: ScopeNavigationWrite[] = [];
  private pendingTimers = new Set<number>();
  private location: ScopeLocationEvent;

  constructor(options: MemoryScopeNavigationOptions = {}) {
    this.clock = options.clock ?? browserClock;
    this.echoDelayMs = options.echoDelayMs ?? 0;
    this.location = freezeSpatialValue({
      scopeCandidate: options.initialScopeCandidate ?? null,
      catalogRevisionCandidate: options.initialCatalogRevisionCandidate ?? null,
      navigationId: null,
    });
  }

  get writes(): readonly ScopeNavigationWrite[] {
    return this.writeLog;
  }

  readScopeCandidate(): string | null {
    return this.location.scopeCandidate;
  }

  writeScope(write: ScopeNavigationWrite): Promise<void> {
    const catalogRevision = parseCatalogRevision(write.catalogRevision);
    const canonicalWrite = freezeSpatialValue({ ...write, catalogRevision });
    this.writeLog.push(canonicalWrite);
    return new Promise<void>((resolve) => {
      const timer = this.clock.setTimeout(() => {
        this.pendingTimers.delete(timer);
        this.publishLocation({
          scopeCandidate: canonicalWrite.scopeKey,
          catalogRevisionCandidate: catalogRevision,
          navigationId: canonicalWrite.navigationId,
        });
        resolve();
      }, this.echoDelayMs);
      this.pendingTimers.add(timer);
    });
  }

  subscribeLocation(listener: (event: ScopeLocationEvent) => void): () => void {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  navigate(event: ScopeLocationEvent): void {
    this.publishLocation(event);
  }

  dispose(): void {
    for (const timer of this.pendingTimers) this.clock.clearTimeout(timer);
    this.pendingTimers = new Set();
    this.listeners.clear();
  }

  private publishLocation(event: ScopeLocationEvent): void {
    this.location = freezeSpatialValue({ ...event });
    for (const listener of [...this.listeners]) listener(this.location);
  }
}
