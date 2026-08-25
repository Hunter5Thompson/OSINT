/**
 * Adapted from God's Eye View, commit 880a672b5e16ad3e41d318801d3a5203f9201923
 * Copyright (c) 2026 Bilawal Sidhu. MIT License — full text in
 * LICENSES/gods-eye-view-MIT.txt. See THIRD_PARTY_NOTICES.md.
 */

export type AllocationStrategy = "ELASTIC" | "WEIGHTED";

export const ALLOCATION_STRATEGIES: readonly AllocationStrategy[] = Object.freeze([
  "ELASTIC",
  "WEIGHTED",
]);

/** Floor for semantic layer weights so a missing/zero weight never zeros a layer. */
const MIN_SEMANTIC_WEIGHT = 0.05;

export const LAYER_LABEL_WEIGHTS = Object.freeze({
  events: 1.4,
  gdacs: 1.3,
  earthquakes: 1.2,
  eonet: 1.0,
  refineries: 0.7,
  datacenters: 0.7,
  pipelines: 0.5,
  cables: 0.5,
}) satisfies Readonly<Record<string, number>>;

export function normalizeAllocationStrategy(
  input: string | undefined,
  fallback: AllocationStrategy = "ELASTIC",
): AllocationStrategy {
  const raw = String(input ?? "")
    .trim()
    .toUpperCase();
  if ((ALLOCATION_STRATEGIES as readonly string[]).includes(raw)) {
    return raw as AllocationStrategy;
  }
  const normalizedFallback = String(fallback ?? "")
    .trim()
    .toUpperCase();
  if ((ALLOCATION_STRATEGIES as readonly string[]).includes(normalizedFallback)) {
    return normalizedFallback as AllocationStrategy;
  }
  return "ELASTIC";
}

function cmpId(a: string, b: string): number {
  return a < b ? -1 : a > b ? 1 : 0;
}

function sumMap(values: Map<string, number>): number {
  let total = 0;
  for (const value of values.values()) total += value;
  return total;
}

/** Round-robin (or ordered) fill of unused capacity among unsaturated layers. */
function redistributeUnused(
  quotas: Map<string, number>,
  demand: ReadonlyMap<string, number>,
  capacity: number,
  order: readonly string[],
): void {
  let used = sumMap(quotas);
  while (used < capacity) {
    let changed = false;
    for (const layerId of order) {
      const current = quotas.get(layerId) ?? 0;
      if (current >= (demand.get(layerId) ?? 0)) continue;
      quotas.set(layerId, current + 1);
      used++;
      changed = true;
      if (used >= capacity) break;
    }
    if (!changed) break;
  }
}

type WeightedEntry = {
  layerId: string;
  count: number;
  weight: number;
  fraction: number;
};

function layerWeight(
  layerId: string,
  count: number,
  layerWeights: Readonly<Record<string, number>>,
): number {
  const semantic = Math.max(MIN_SEMANTIC_WEIGHT, Number(layerWeights[layerId]) || 1);
  return Math.sqrt(count) * semantic;
}

/**
 * Iterative weighted apportionment: each round recomputes shares over unsaturated
 * layers so freed capacity stays weighted (not round-robin). Hamilton remainder
 * runs each round; when no whole seats land, remainder then break.
 */
function apportionWeighted(
  quotas: Map<string, number>,
  demand: ReadonlyMap<string, number>,
  entries: WeightedEntry[],
  remaining: number,
): number {
  const maxRounds = demand.size + 1;
  for (let round = 0; round < maxRounds && remaining > 0; round++) {
    const open = entries.filter((entry) => (quotas.get(entry.layerId) ?? 0) < entry.count);
    if (open.length === 0) break;

    const totalWeight = open.reduce((sum, entry) => sum + entry.weight, 0);
    if (totalWeight <= 0) break;

    let placed = 0;
    for (const entry of open) {
      const exact = (remaining * entry.weight) / totalWeight;
      const room = entry.count - (quotas.get(entry.layerId) ?? 0);
      const whole = Math.min(room, Math.floor(exact));
      if (whole > 0) {
        quotas.set(entry.layerId, (quotas.get(entry.layerId) ?? 0) + whole);
        placed += whole;
      }
      entry.fraction = exact - Math.floor(exact);
    }
    remaining -= placed;

    // Hamilton largest-remainder for this round's fractional parts.
    open.sort(
      (a, b) =>
        b.fraction - a.fraction || b.weight - a.weight || cmpId(a.layerId, b.layerId),
    );
    for (const entry of open) {
      if (remaining <= 0) break;
      const current = quotas.get(entry.layerId) ?? 0;
      if (current >= entry.count) continue;
      quotas.set(entry.layerId, current + 1);
      remaining--;
    }

    if (placed === 0) break;
  }
  return remaining;
}

export function allocateLayerQuotas(
  demandByLayer: ReadonlyMap<string, number>,
  capacity: number,
  strategy: AllocationStrategy = "ELASTIC",
  layerWeights: Readonly<Record<string, number>> = LAYER_LABEL_WEIGHTS,
): Map<string, number> {
  const layers = [...demandByLayer.entries()]
    .filter(([, n]) => n > 0)
    .map(([id, n]): [string, number] => [id, Math.floor(n)])
    .filter(([, n]) => n > 0)
    .sort(([a], [b]) => cmpId(a, b));

  const quotas = new Map<string, number>(layers.map(([id]) => [id, 0]));
  if (layers.length === 0) return quotas;

  const totalDemand = layers.reduce((sum, [, n]) => sum + n, 0);
  const cap = Math.min(Math.max(0, Math.floor(capacity)), totalDemand);
  if (cap === 0) return quotas;

  const demand = new Map(layers);
  const ids = layers.map(([id]) => id);
  const normalized = normalizeAllocationStrategy(strategy);

  if (normalized === "ELASTIC") {
    const n = ids.length;
    const base = Math.floor(cap / n);
    let remainder = cap % n;
    for (const layerId of ids) {
      const entitlement = base + (remainder > 0 ? 1 : 0);
      if (remainder > 0) remainder--;
      quotas.set(layerId, Math.min(demand.get(layerId) ?? 0, entitlement));
    }
    redistributeUnused(quotas, demand, cap, ids);
    return quotas;
  }

  const entries: WeightedEntry[] = layers.map(([layerId, count]) => ({
    layerId,
    count,
    weight: layerWeight(layerId, count, layerWeights),
    fraction: 0,
  }));

  const priorityOrder = [...entries]
    .sort((a, b) => b.weight - a.weight || cmpId(a.layerId, b.layerId))
    .map((entry) => entry.layerId);

  let remaining = cap;
  if (cap >= ids.length) {
    for (const layerId of ids) quotas.set(layerId, 1);
    remaining -= ids.length;
  }

  if (remaining > 0) {
    apportionWeighted(quotas, demand, entries, remaining);
  }

  redistributeUnused(quotas, demand, cap, priorityOrder);
  return quotas;
}
