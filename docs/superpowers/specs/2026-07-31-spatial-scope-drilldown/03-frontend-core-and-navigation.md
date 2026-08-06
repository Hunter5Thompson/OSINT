# Teil-Spec 03 — Frontend-Core und Navigation

> **Parent:** [Spatial-Scope-Index](../2026-07-31-spatial-scope-drilldown-design.md)
>
> **Normativer Besitz:** frameworkfreies TypeScript-Interface, State Machine,
> Generation Guards, Lifecycle, React-Adapter sowie URL- und History-Semantik.
>
> **Voraussetzungen:** [01 — Architektur](01-architecture-and-invariants.md) und
> [02 — Scope-Identität](02-scope-identity-and-boundary-policy.md). Der konkrete
> Catalog-Port wird in [04](04-spatial-catalog-contracts.md) spezifiziert.

---

## 8. Frontend-Core: exakter Vertrag

### 8.1 Öffentliche Typen

```ts
declare const scopeKeyBrand: unique symbol;

export type ScopeKey = string & {
  readonly [scopeKeyBrand]: "ScopeKey";
};

export type ScopeKind = "world" | "country" | "admin1" | "admin2";

export type ScopeCause =
  | "country-click"
  | "child-click"
  | "breadcrumb"
  | "keyboard"
  | "search"
  | "browser-history"
  | "deep-link"
  | "programmatic";

export type EnterCause = Exclude<
  ScopeCause,
  "browser-history" | "deep-link"
>;

export interface ScopeSummary {
  readonly key: ScopeKey;
  readonly kind: ScopeKind;
  readonly label: string;
  readonly shortLabel: string;
  readonly parentKey: ScopeKey | null;
  readonly childrenAvailable: boolean;
  readonly presentation: "boundary" | "semantic-only";
}

export type ScopePath = readonly [ScopeSummary, ...ScopeSummary[]];

export interface SpatialQueryRef {
  readonly schemaVersion: 1;
  readonly scopeKey: ScopeKey;
  readonly catalogRevision: string;
  readonly boundaryPolicy: string;
}

export interface ScopeProblem {
  readonly severity: "warning" | "error";
  readonly code:
    | "INVALID_SCOPE_KEY"
    | "UNKNOWN_SCOPE"
    | "CATALOG_UNAVAILABLE"
    | "CATALOG_REVISION_UNAVAILABLE"
    | "INVALID_LINEAGE"
    | "GEOMETRY_UNAVAILABLE"
    | "ASSET_LIMIT_EXCEEDED"
    | "ASSET_BUSY"
    | "PRESENTATION_FAILED"
    | "URL_SYNC_FAILED";
  readonly target: string | null;
  readonly recoverable: boolean;
  readonly message: string;
  readonly activeCatalogRevision: CatalogRevision | null;
}

export type ScopeVisualState =
  | { readonly phase: "none"; readonly stateRevision: null }
  | { readonly phase: "building"; readonly stateRevision: number }
  | { readonly phase: "ready"; readonly stateRevision: number }
  | {
      readonly phase: "unavailable";
      readonly stateRevision: number;
      readonly problem: ScopeProblem;
    };

export type SpatialScopeSnapshot =
  | {
      readonly phase: "hydrating";
      readonly stateRevision: 0;
      readonly current: null;
      readonly path: readonly [];
      readonly query: null;
      readonly pending: ScopeKey | null;
      readonly problem: ScopeProblem | null;
      readonly visual: { readonly phase: "none"; readonly stateRevision: null };
    }
  | {
      readonly phase: "ready" | "resolving";
      readonly stateRevision: number;
      readonly current: ScopeSummary;
      readonly path: ScopePath;
      readonly query: SpatialQueryRef;
      readonly pending: ScopeKey | null;
      readonly problem: ScopeProblem | null;
      readonly visual: ScopeVisualState;
    };
```

`ScopeKind` und `SpatialQueryRef` werden nur in `spatial/contracts.ts` deklariert.
Timeline-, Cesium- und Intelligence-Frontend-Code importieren diese Typen; die
semantisch erlaubten Kinds besitzt [§7.2](02-scope-identity-and-boundary-policy.md#72-unterstützte-kinds).

Die diskriminierte Hydration verhindert einen kurzen globalen CHRONIK-/Munin-Request, während ein Deep Link noch aufgelöst wird. Caller müssen `query === null` explizit behandeln und dürfen dann nicht laden.

### 8.2 Commands und Ergebnisse

```ts
export type SpatialScopeCommand =
  | {
      readonly type: "enter";
      readonly target: ScopeKey;
      readonly cause: EnterCause;
    }
  | {
      readonly type: "ascend";
      readonly cause: "breadcrumb" | "keyboard";
    }
  | {
      readonly type: "hydrate";
      readonly target: ScopeKey | null;
      readonly catalogRevision: string | null;
      readonly cause: "browser-history" | "deep-link";
    }
  | {
      readonly type: "prefetch";
      readonly target: ScopeKey;
      readonly priority: "hover" | "anticipated";
    }
  | { readonly type: "rehydrate" };

export type SpatialScopeResult =
  | { readonly outcome: "committed"; readonly snapshot: SpatialScopeSnapshot }
  | { readonly outcome: "unchanged"; readonly snapshot: SpatialScopeSnapshot }
  | { readonly outcome: "superseded" }
  | { readonly outcome: "cancelled" }
  | { readonly outcome: "prefetched"; readonly target: ScopeKey }
  | { readonly outcome: "failed"; readonly problem: ScopeProblem };

export interface DispatchOptions {
  readonly signal?: AbortSignal;
}

export interface SpatialScopeModule {
  getSnapshot(): SpatialScopeSnapshot;
  subscribe(listener: () => void): () => void;
  dispatch(
    command: SpatialScopeCommand,
    options?: DispatchOptions,
  ): Promise<SpatialScopeResult>;
}

interface OwnedSpatialScopeModule extends SpatialScopeModule {
  start(): void;
  stop(): void;
}
```

Das ist die vollständige primäre Caller-Interface. Nur der Provider besitzt zusätzlich
den Lifecycle `start/stop`; Context-Consumer sehen ihn nicht. Es gibt keine öffentliche
Methode für BBox, GeoJSON, Cesium, History-Push oder Qdrant-Filter.

`activeCatalogRevision` ist ausschließlich strukturierter Vertrag und wird niemals
aus `message` extrahiert. `rehydrate` besitzt absichtlich keine Caller-Parameter: Der
Controller übernimmt Ziel und aktive Revision nur aus dem weiterhin committed
Snapshot und dessen validiertem `CATALOG_REVISION_UNAVAILABLE`-Problem. Ohne dieses
Problem ist der Command idempotent `unchanged`.

### 8.3 React-Adapter

`useSpatialScope()` ist ein dünner `useSyncExternalStore`-Adapter. Er darf nur ergonomische Wrapper bilden:

```ts
export type SpatialScopeHandle = SpatialScopeSnapshot & {
  enter(target: ScopeKey, cause: EnterCause): Promise<SpatialScopeResult>;
  ascend(cause: "breadcrumb" | "keyboard"): Promise<SpatialScopeResult>;
  prefetch(target: ScopeKey): Promise<SpatialScopeResult>;
  rehydrate(): Promise<SpatialScopeResult>;
};
```

`reset()` ist kein zusätzliches Core-Konzept; der Hook kann `enter(WORLD_SCOPE_KEY, "programmatic")` anbieten. Browser-Back bleibt beim Router/History-Adapter.

Der Hook reicht keine möglicherweise ungebundene Klassenmethode direkt an React. Er
hält für die Lebensdauer derselben Module-Instanz stabile Wrapper:

```ts
const subscribe = useCallback(
  (listener: () => void) => module.subscribe(listener),
  [module],
);
const getSnapshot = useCallback(() => module.getSnapshot(), [module]);

return useSyncExternalStore(
  subscribe,
  getSnapshot,
  getStableHydratingSnapshot,
);
```

`getStableHydratingSnapshot` liefert immer denselben eingefrorenen Singleton. Das
Module cached auch sein aktuelles Snapshot-Objekt und gibt bis zur nächsten
Publikation dieselbe Referenz zurück. Damit entstehen weder ein verlorenes `this`,
Endlos-Rendern noch Tearing durch bei jedem Read neu erzeugte Objekte.

### 8.4 Snapshot-Invarianten

Für jeden nicht-hydrierenden Snapshot gilt:

1. `path.length >= 1`.
2. `path[0].key === WORLD_SCOPE_KEY`.
3. `path.at(-1)?.key === current.key`.
4. Jeder Eintrag ist laut exakt derselben Katalogrevision der kanonische Parent des nächsten.
5. `query.scopeKey === current.key`.
6. `stateRevision` steigt ausschließlich bei einem semantischen Commit.
7. `pending` ist niemals Query-Source-of-Truth.
8. Während `phase === "resolving"` bleiben `current`, `path` und `query` vollständig auf der alten committed Revision.
9. Geometrie ist in keinem Snapshot enthalten.
10. Ein Presentation-Fehler rollt einen semantischen Commit nicht zurück.
11. `visual.stateRevision` ist entweder `null` oder bezieht sich exakt auf einen
    committed `stateRevision`; Completion für ältere Revisionen wird verworfen.
12. Änderungen an `pending`, `problem` oder `visual` dürfen einen neuen Snapshot
    publizieren, erhöhen aber `stateRevision` nicht.

### 8.5 Übergangsalgorithmus

Foreground-Commands verwenden eine monotone Intent-Generation und „last intent wins“:

```ts
async function enterScope(
  command: EnterCommand,
  outerSignal?: AbortSignal,
): Promise<SpatialScopeResult> {
  const intent = beginForegroundIntent(command.target, outerSignal);
  publishResolving(command.target);

  try {
    const resolved = await catalog.resolve(
      command.target,
      resolutionRevisionFor(command, getSnapshot()),
      intent.signal,
    );
    assertCurrentIntent(intent);
    validateLineage(resolved);

    await navigation.writeScope({
      scopeKey: resolved.scope.key,
      catalogRevision: resolved.query.catalogRevision,
      mode: navigationModeFor(command),
      navigationId: intent.navigationId,
    });
    assertCurrentIntent(intent);

    const next = commitResolvedScope(resolved); // also sets visual building/unavailable
    if (resolved.presentation.mode === "boundary") {
      const visualSignal = beginPresentationLifetime(next.stateRevision);
      void observePresentation(
        presentation.present(
          resolved.presentation,
          next.stateRevision,
          visualSignal,
        ),
        next.stateRevision,
      );
    }
    return { outcome: "committed", snapshot: next };
  } catch (error: unknown) {
    return finishTransitionError(intent, error);
  }
}
```

Das Pseudocode-Beispiel ist normativ in seiner Reihenfolge, nicht in Funktionsnamen.

Feinregeln:

- Vor und nach jedem `await` wird Generation plus Abort geprüft.
- Ein neues Foreground-Intent abortet das alte. Das alte darf danach weder Store noch URL noch Cesium mutieren.
- Der Resolve-Signal-Lifetime endet mit dem Transition-Intent. Nach dem Commit besitzt
  die Darstellung einen separaten, vom Controller gehaltenen AbortController. Er wird
  erst beim nächsten semantischen Commit oder bei `stop()` abgebrochen; ein Caller,
  der seinen Dispatch-Signal nach erfolgreicher Rückgabe abbricht, darf die committed
  Darstellung nicht zerstören.
- Ein bloß begonnener Resolve für den nächsten Scope lässt die Darstellung des noch
  committed Scope weiterlaufen. Erst der nächste Commit versteckt/abortet sie.
- `enter(current.key)` ist `unchanged` und schreibt keinen History-Eintrag.
- `ascend()` berechnet das Ziel aus dem committed Parent. Während eines pending Drilldowns steigt es nicht aus dessen noch uncommitted Lineage auf.
- `ascend()` am Root ist `unchanged`; es cancelt aber einen eventuell pending Drilldown.
- Zwei Resolver für dasselbe Ziel dürfen den HTTP-Request teilen. Transition-Intent und History-Semantik werden trotzdem nicht zusammengelegt.
- URL-Writes laufen über den React-Router-Adapter und können asynchron abschließen.
  Wird ein Intent nach erfolgreichem URL-Write superseded, repariert der
  Navigation-Coordinator die URL per Replace auf den letzten committed oder bereits
  neueren gewünschten Scope. Ein stale Write darf nicht als externer Hydrate-Intent
  zurück in den Controller gespiegelt werden.
- Prefetch besitzt keine Commit-Rechte, keine Foreground-Generation und keine URL-/Kamera-Wirkung.
- Prefetch und Navigation teilen einen ref-counted In-flight-Load. Das Abbrechen des Hover-Consumers beendet den Request nicht, wenn der Click-Consumer ihn übernommen hat.
- Operationelle Fehler rejecten das Promise nicht. Nur Programmierfehler wie ein Hook außerhalb des Providers dürfen werfen.
- Abort durch einen neueren Foreground-Intent liefert `superseded`; Abort durch den
  übergebenen Caller-Signal oder `stop()` ohne neueren Intent liefert `cancelled`.
- Ungültige Lineage, unbekannter Scope oder Katalogausfall lassen State und URL unverändert.
- Fehlende Geometrie ist ein semantisch erfolgreicher Commit mit `presentation: "semantic-only"` und Warning.
- Ein Revisions-409 publiziert die typisierte aktive Revision, committet nichts und
  retryt nicht. Erst der parameterlose, sichtbare `rehydrate`-Command löst den aktuell
  committed Scope über `SpatialCatalogPort.rehydrate` gegen diese Revision auf,
  ersetzt den Router-State und committet anschließend Scope, Query und Revision
  gemeinsam. 404, erneuter 409 und Katalogfehler bleiben sichtbar und fail-closed.
- Auch Rehydrate prüft Foreground-Generation und Abort vor und nach jedem Await. Ein
  bereits abgebrochener Command ruft den Adapter nicht auf; eine verspätete Antwort
  besitzt keine Commit-, URL- oder Presentation-Rechte.

### 8.6 Subscription- und Effect-Ordnung

Der Store-Commit ist lokal atomar. Cesium, CHRONIK und Munin sind keine verteilte Transaktion. Die korrekte Garantie lautet:

1. Der neue semantische Snapshot wird einmal veröffentlicht.
2. Bei vorhandener Boundary startet `visual.phase="building"`; ohne Boundary startet
   `visual.phase="unavailable"` mit `GEOMETRY_UNAVAILABLE`.
3. Jeder Consumer übernimmt `stateRevision` und `SpatialQueryRef` als Generation.
4. Alte Consumer-Ergebnisse werden beim Scope-Wechsel sofort als unzulässig markiert.
5. Nur Ergebnisse mit derselben `scopeKey + catalogRevision + consumerRequestGeneration` dürfen sichtbar werden.
6. Cesium darf `visual` nur für die dazugehörige `stateRevision` auf `ready` oder
   `unavailable` setzen.
7. Ein Consumer-Fehler verändert nicht den semantischen Scope; er wird scope-spezifisch angezeigt.

Damit entsteht Konvergenz mit expliziten Revision Guards statt einer falschen Behauptung globaler Atomizität.

`start()` und `stop()` sind idempotent und wechselweise mehrfach aufrufbar, damit
React-StrictMode-Effect-Replay denselben Controller nicht in einen irreversibel
disposed Zustand bringt. `stop()` abortet Foreground/Prefetch/Presentation, entfernt
Router-/Cesium-Listener, leert ref-counted Leases und publiziert wieder den stabilen
Hydration-Snapshot. Ein nachfolgendes `start()` initialisiert aus der aktuellen Router-
Location neu.

---

## 9. URL, Deep Links und Navigation

### 9.1 Kanonisches URL-Format

```text
/worldview                              => world
/worldview?scope=country%3AUKR          => country:UKR
/worldview?scope=admin1%3Aiso3166-2%3AUA-14
```

- `world` wird kanonisch ohne `scope`-Parameter geschrieben.
- Die URL enthält nur den Scope-Key, niemals Lineage, Geometrie, BBox oder Display-Name.
- Der bestehende Legacy-Redirect von `/` nach `/worldview` behandelt `scope` wie
  `entity`/`layer` und erhält den vollständigen Query-String.
- `layer`, `filter`, `entity` und unbekannte fremde Parameter bleiben unverändert.
- Ein erfolgreicher User-Intent (`enter`, Breadcrumb, Keyboard-Ascend) erzeugt eine
  React-Router-Push-Navigation.
- Browser Back/Forward beziehungsweise eine andere Router-Navigation erzeugt intern
  `hydrate` und niemals einen weiteren History-Eintrag.
- Die Hierarchie wird immer aus dem Katalog rekonstruiert.

### 9.2 Initiale Hydration

1. Provider startet im diskriminierten `hydrating`-State.
2. URL-Adapter dekodiert und validiert maximal einen `scope`-Wert.
3. Ohne Parameter wird `world` aus dem eingebetteten Bootstrap oder Katalog aufgelöst.
4. Mit Parameter wird exakt dieser Scope aufgelöst.
5. Erst nach erfolgreichem Resolve wird der erste Query-Token publiziert.
6. Ein ungültiger Initial-Link fällt auf `world` zurück, entfernt ausschließlich
   `scope` per React-Router-Replace und zeigt `INVALID_SCOPE_KEY` oder `UNKNOWN_SCOPE`
   sichtbar an.

### 9.3 Popstate-Fehler

Schlägt die Auflösung einer historischen URL fehl, bleibt der bisher committed Scope
aktiv. Der URL-Adapter repariert die URL per React-Router-Replace auf diesen Scope und
publiziert eine Warning. Es gibt keinen stillen globalen Fallback.

### 9.4 URL-Port

```ts
interface ScopeNavigationWrite {
  readonly scopeKey: ScopeKey | null;
  readonly catalogRevision: string;
  readonly mode: "push" | "replace";
  readonly navigationId: string;
}

interface ScopeLocationEvent {
  readonly scopeCandidate: string | null;
  readonly catalogRevisionCandidate: string | null;
  readonly navigationId: string | null;
}

interface ScopeNavigationPort {
  readScopeCandidate(): string | null;
  writeScope(write: ScopeNavigationWrite): Promise<void>;
  subscribeLocation(listener: (event: ScopeLocationEvent) => void): () => void;
}
```

Produktion nutzt `ReactRouterScopeNavigation`; Tests nutzen
`MemoryScopeNavigation`. Der Produktionsadapter wird an den vorhandenen
`createBrowserRouter` gebunden, verwendet dessen Navigate/Subscribe-Mechanismus und
schreibt nicht direkt an React Router vorbei in `window.history`. Er erhält alle
fremden Search-Parameter, `pathname`, `hash` und vorhandenen Location-State; im State
ergänzt er nur eine eindeutige `odinSpatialNavigationId` und die dazugehörige
`odinSpatialCatalogRevision`.

Zur Vermeidung eines Importzyklus importiert `spatial/navigation.ts` nicht den
Router-Singleton (dessen Route bereits `WorldviewPage` importiert). Ein kleiner Bridge-
Teil in `spatial/react.tsx` liest `useLocation`, schreibt über `useNavigate` und meldet
Änderungen aus einem Effect an den Adapter. Der Adapter selbst bleibt in Tests ohne
React Router instanziierbar.

Reads liefern absichtlich einen untrusted `string`-Candidate, keinen gebrandeten
`ScopeKey`. Erst `parseScopeKeyCandidate()` normalisiert/validiert und erzeugt den
Brand. Writes akzeptieren dagegen nur bereits validierte `ScopeKey`.

Der Controller hält die Menge seiner aktuell pending Navigation-IDs. Ein Location-
Event mit einer solchen ID ist das Echo des eigenen Writes und wird nicht hydriert.
Ein späteres Browser-Back auf denselben historischen Eintrag trägt zwar die alte ID,
sie ist dann aber nicht mehr pending und wird korrekt als externe Navigation behandelt.
Writes werden im Adapter serialisiert und nach jedem Abschluss gegen den jüngsten
gewünschten Scope geprüft; dadurch kann ein verspätetes A niemals einen neueren B-
Location-State überschreiben. React-Caller erhalten diesen Port nicht.

`writeScope()` löst erst auf, wenn die Bridge den passenden Navigation-ID-Echo gesehen
hat; der Rückgabewert von `useNavigate` allein ist im Browser-Modus nicht die Commit-
Bestätigung. Bleibt das Echo zwei Sekunden aus oder stoppt der Provider, folgt
`URL_SYNC_FAILED`/Cancel und kein semantischer Commit. Timer werden mit einer
injizierbaren Clock getestet, nicht mit realen Sleeps.

Die Revision bleibt aus der sichtbaren URL heraus: ein geteilter/reloadeter Deep Link
resolved gegen active, während Browser Back innerhalb derselben Session die im Router-
State gepinnte Revision anfordern kann. Auch dieser State ist untrusted und muss gegen
`CatalogRevision` validiert sowie vom Backend bedient werden.

---
