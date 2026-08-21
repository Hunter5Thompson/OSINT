import type {
  ScopeKey,
  SpatialScopeResult,
} from "./contracts";

export interface CountrySelection {
  readonly scopeKey: ScopeKey;
  readonly label: string;
}

export interface SelectionEnvelope<T> {
  readonly selection: T;
  readonly selectedAtScopeStateRevision: number;
  readonly verifiedScopeKey: ScopeKey | null;
}

function committedSnapshotForTarget(
  result: SpatialScopeResult,
  target: ScopeKey,
) {
  if (
    result.outcome !== "committed"
    || result.snapshot.phase === "hydrating"
    || result.snapshot.current.key !== target
  ) {
    return null;
  }
  return result.snapshot;
}

function countrySelectionFromResult(
  result: SpatialScopeResult,
  target: ScopeKey,
): CountrySelection | null {
  const snapshot = committedSnapshotForTarget(result, target);
  if (snapshot === null || snapshot.current.kind !== "country") return null;
  return Object.freeze({
    scopeKey: snapshot.current.key,
    label: snapshot.current.label,
  });
}

export function createSelectionEnvelope<T>(
  selection: T,
  selectedAtScopeStateRevision: number,
  verifiedScopeKey: ScopeKey | null = null,
): SelectionEnvelope<T> {
  return Object.freeze({
    selection,
    selectedAtScopeStateRevision,
    verifiedScopeKey,
  });
}

export function selectionForScopeRevision<T>(
  envelope: SelectionEnvelope<T> | null,
  currentStateRevision: number,
  currentScopeKey: ScopeKey,
): T | null {
  if (envelope === null) return null;
  if (envelope.verifiedScopeKey !== null) {
    return envelope.verifiedScopeKey === currentScopeKey
      ? envelope.selection
      : null;
  }
  return envelope.selectedAtScopeStateRevision === currentStateRevision
    ? envelope.selection
    : null;
}

export async function commitSpatialChildSelection(
  target: ScopeKey,
  enter: () => Promise<SpatialScopeResult>,
): Promise<CountrySelection | null> {
  const result = await enter();
  return countrySelectionFromResult(result, target);
}

export async function openSpatialChild(
  target: ScopeKey,
  enter: () => Promise<SpatialScopeResult>,
  commitSelection: (selection: CountrySelection | null) => void,
  clearCircleSpotlight: () => void,
): Promise<boolean> {
  const result = await enter();
  if (committedSnapshotForTarget(result, target) === null) return false;
  commitSelection(countrySelectionFromResult(result, target));
  clearCircleSpotlight();
  return true;
}
