// Internal catalog implementation; consumers use ../catalog.ts.
import {
  type SpatialCatalogPort,
  type CatalogRevision,
  type ResolvedScope,
  type ScopeKey,
  parseCatalogRevision,
  freezeSpatialValue,
} from "../contracts";
import {
  type DeferredGate,
  abortError,
  type MemoryResolveCall,
  type MemoryPrefetchCall,
  type MemorySpatialCatalogOptions,
  contractError,
  SpatialCatalogError,
} from "./core";
import {
  parseResolvedScope,
} from "./metadata";

function createDeferredGate(): DeferredGate {
  let resolvePromise: () => void = () => undefined;
  let rejectPromise: (error?: unknown) => void = () => undefined;
  const promise = new Promise<void>((resolve, reject) => {
    resolvePromise = resolve;
    rejectPromise = reject;
  });
  return { promise, resolve: resolvePromise, reject: rejectPromise };
}

async function waitForGate(gate: DeferredGate | undefined, signal: AbortSignal): Promise<void> {
  if (signal.aborted) throw abortError();
  if (gate === undefined) return;
  await new Promise<void>((resolve, reject) => {
    const onAbort = () => reject(abortError());
    signal.addEventListener("abort", onAbort, { once: true });
    gate.promise.then(resolve, reject).finally(() => signal.removeEventListener("abort", onAbort));
  });
  if (signal.aborted) throw abortError();
}

export class MemorySpatialCatalog implements SpatialCatalogPort {
  private readonly activeCatalogRevision: CatalogRevision;
  private readonly entries = new Map<string, ResolvedScope>();
  private readonly revisions = new Set<CatalogRevision>();
  private readonly resolveGates = new Map<ScopeKey, DeferredGate[]>();
  private readonly resolveCallLog: MemoryResolveCall[] = [];
  private readonly prefetchCallLog: MemoryPrefetchCall[] = [];
  private disposed = false;

  constructor(options: MemorySpatialCatalogOptions) {
    this.activeCatalogRevision = parseCatalogRevision(options.activeCatalogRevision);
    for (const candidate of options.resolvedScopes) {
      const resolved = parseResolvedScope(candidate);
      const mapKey = this.entryKey(resolved.scope.key, resolved.query.catalogRevision);
      if (this.entries.has(mapKey)) contractError(`duplicate memory catalog entry: ${mapKey}`);
      this.entries.set(mapKey, resolved);
      this.revisions.add(resolved.query.catalogRevision);
    }
    if (!this.revisions.has(this.activeCatalogRevision)) {
      contractError("active catalog revision has no resolved scopes", this.activeCatalogRevision);
    }
  }

  get resolveCalls(): readonly MemoryResolveCall[] {
    return this.resolveCallLog;
  }

  get prefetchCalls(): readonly MemoryPrefetchCall[] {
    return this.prefetchCallLog;
  }

  deferNextResolve(scopeKey: ScopeKey): DeferredGate {
    const gate = createDeferredGate();
    const gates = this.resolveGates.get(scopeKey) ?? [];
    gates.push(gate);
    this.resolveGates.set(scopeKey, gates);
    return gate;
  }

  async resolve(
    scopeKey: ScopeKey,
    catalogRevision: string | null,
    signal: AbortSignal,
  ): Promise<ResolvedScope> {
    this.assertAvailable();
    const revision = this.requestedRevision(catalogRevision);
    this.resolveCallLog.push(freezeSpatialValue({ scopeKey, catalogRevision: revision }));
    const gates = this.resolveGates.get(scopeKey);
    const gate = gates?.shift();
    if (gates?.length === 0) this.resolveGates.delete(scopeKey);
    await waitForGate(gate, signal);
    this.assertAvailable();
    const result = this.entries.get(this.entryKey(scopeKey, revision));
    if (result === undefined) {
      throw new SpatialCatalogError({
        code: "UNKNOWN_SCOPE",
        target: scopeKey,
        message: "Scope is not present in the catalog.",
      });
    }
    return result;
  }

  async prefetch(
    scopeKey: ScopeKey,
    catalogRevision: string,
    priority: "hover" | "anticipated",
    signal: AbortSignal,
  ): Promise<void> {
    this.assertAvailable();
    if (signal.aborted) throw abortError();
    const revision = this.requestedRevision(catalogRevision);
    this.prefetchCallLog.push(freezeSpatialValue({ scopeKey, catalogRevision: revision, priority }));
    if (!this.entries.has(this.entryKey(scopeKey, revision))) {
      throw new SpatialCatalogError({
        code: "UNKNOWN_SCOPE",
        target: scopeKey,
        message: "Scope is not present in the catalog.",
      });
    }
    await Promise.resolve();
    if (signal.aborted) throw abortError();
  }

  async rehydrate(
    scopeKey: ScopeKey,
    activeCatalogRevision: CatalogRevision,
    signal: AbortSignal,
  ): Promise<ResolvedScope> {
    this.assertAvailable();
    if (signal.aborted) throw abortError();
    if (activeCatalogRevision !== this.activeCatalogRevision) {
      throw new SpatialCatalogError({
        code: "CATALOG_REVISION_UNAVAILABLE",
        target: activeCatalogRevision,
        message: "Catalog recovery revision is no longer active.",
        recoverable: true,
        activeCatalogRevision: this.activeCatalogRevision,
      });
    }
    return this.resolve(scopeKey, activeCatalogRevision, signal);
  }

  dispose(): void {
    this.disposed = true;
    for (const gates of this.resolveGates.values()) {
      gates.forEach((gate) => gate.reject(abortError()));
    }
    this.resolveGates.clear();
  }

  private requestedRevision(candidate: string | null): CatalogRevision {
    let revision: CatalogRevision;
    try {
      revision = candidate === null ? this.activeCatalogRevision : parseCatalogRevision(candidate);
    } catch (error: unknown) {
      throw new SpatialCatalogError({
        code: "CATALOG_REVISION_UNAVAILABLE",
        target: candidate,
        message: "Catalog revision is invalid or unavailable.",
        recoverable: true,
        activeCatalogRevision: this.activeCatalogRevision,
        cause: error,
      });
    }
    if (!this.revisions.has(revision)) {
      throw new SpatialCatalogError({
        code: "CATALOG_REVISION_UNAVAILABLE",
        target: revision,
        message: "Catalog revision is invalid or unavailable.",
        recoverable: true,
        activeCatalogRevision: this.activeCatalogRevision,
      });
    }
    return revision;
  }

  private entryKey(scopeKey: ScopeKey, revision: CatalogRevision): string {
    return `${revision}\u0000${scopeKey}`;
  }

  private assertAvailable(): void {
    if (this.disposed) {
      throw new SpatialCatalogError({
        code: "CATALOG_UNAVAILABLE",
        message: "Memory spatial catalog has been disposed.",
      });
    }
  }
}
