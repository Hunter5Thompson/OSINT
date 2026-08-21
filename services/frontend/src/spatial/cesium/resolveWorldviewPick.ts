import {
  parseScopeKeyCandidate,
  type ScopeKey,
} from "../contracts";

const DRILL_PICK_LIMIT = 16;

type JsonRecord = Record<string, unknown>;

export interface SpatialChildPickId {
  readonly odinKind: "spatial-child";
  readonly scopeKey: ScopeKey;
  readonly stateRevision: number;
}

export type WorldviewPickCategory =
  | "ui"
  | "operational"
  | "legacy-country"
  | "terrain";

export type ResolvedWorldviewPick =
  | { readonly kind: "ui"; readonly hit: unknown }
  | { readonly kind: "operational"; readonly hit: unknown }
  | {
      readonly kind: "spatial-child";
      readonly id: SpatialChildPickId;
      readonly hit: unknown;
    }
  | { readonly kind: "legacy-country"; readonly hit: unknown }
  | { readonly kind: "terrain"; readonly hit: unknown }
  | { readonly kind: "blank" };

export interface DrillPickScene<TPosition = unknown> {
  drillPick(position: TPosition, limit: number): readonly unknown[];
}

export interface ResolveWorldviewPickOptions {
  readonly stateRevision: number;
  readonly spatialEnabled: boolean;
  readonly classify?: (hit: unknown) => WorldviewPickCategory | null;
  readonly onSaturated?: () => void;
}

function asRecord(value: unknown): JsonRecord | null {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? value as JsonRecord
    : null;
}

function taggedValues(hit: unknown): readonly unknown[] {
  const record = asRecord(hit);
  if (record === null) return [hit];
  return [record.id, record.primitive, hit];
}

export function isSpatialChildPickId(value: unknown): value is SpatialChildPickId {
  const record = asRecord(value);
  if (
    record?.odinKind !== "spatial-child"
    || typeof record.scopeKey !== "string"
    || !Number.isSafeInteger(record.stateRevision)
    || (record.stateRevision as number) < 1
  ) {
    return false;
  }
  try {
    return parseScopeKeyCandidate(record.scopeKey) === record.scopeKey;
  } catch {
    return false;
  }
}

function spatialChildId(hit: unknown): SpatialChildPickId | null {
  for (const value of taggedValues(hit)) {
    if (isSpatialChildPickId(value)) return value;
  }
  return null;
}

function defaultCategory(hit: unknown): WorldviewPickCategory | null {
  for (const value of taggedValues(hit)) {
    const record = asRecord(value);
    if (
      record?.odinKind === "ui"
      || record?.odinKind === "operational"
      || record?.odinKind === "legacy-country"
      || record?.odinKind === "terrain"
    ) {
      return record.odinKind;
    }
  }
  return null;
}

function firstCategory(
  hits: readonly unknown[],
  category: WorldviewPickCategory,
  classify: (hit: unknown) => WorldviewPickCategory | null,
): unknown | null {
  return hits.find((hit) => classify(hit) === category) ?? null;
}

export function resolveWorldviewPick<TPosition>(
  scene: DrillPickScene<TPosition>,
  position: TPosition,
  options: ResolveWorldviewPickOptions,
): ResolvedWorldviewPick {
  const hits = scene.drillPick(position, DRILL_PICK_LIMIT);
  if (hits.length === DRILL_PICK_LIMIT) options.onSaturated?.();
  const classify = options.classify ?? defaultCategory;

  const ui = firstCategory(hits, "ui", classify);
  if (ui !== null) return { kind: "ui", hit: ui };

  const operational = firstCategory(hits, "operational", classify);
  if (operational !== null) return { kind: "operational", hit: operational };

  if (options.spatialEnabled) {
    for (const hit of hits) {
      const id = spatialChildId(hit);
      if (id?.stateRevision === options.stateRevision) {
        return { kind: "spatial-child", id, hit };
      }
    }
  }

  if (!options.spatialEnabled) {
    const legacy = firstCategory(hits, "legacy-country", classify);
    if (legacy !== null) return { kind: "legacy-country", hit: legacy };
  }

  const terrain = firstCategory(hits, "terrain", classify);
  if (terrain !== null) return { kind: "terrain", hit: terrain };
  return { kind: "blank" };
}
