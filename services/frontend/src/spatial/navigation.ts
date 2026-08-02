import {
  freezeSpatialValue,
  parseCatalogRevision,
  type ScopeLocationEvent,
  type ScopeNavigationPort,
  type ScopeNavigationWrite,
} from "./contracts";

export interface ScopeNavigationClock {
  setTimeout(callback: () => void, delayMs: number): number;
  clearTimeout(id: number): void;
}

const browserClock: ScopeNavigationClock = {
  setTimeout: (callback, delayMs) => window.setTimeout(callback, delayMs),
  clearTimeout: (id) => window.clearTimeout(id),
};

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
