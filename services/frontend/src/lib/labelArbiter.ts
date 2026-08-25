/**
 * Adapted from God's Eye View, commit 880a672b5e16ad3e41d318801d3a5203f9201923
 * Copyright (c) 2026 Bilawal Sidhu. MIT License — full text in
 * LICENSES/gods-eye-view-MIT.txt. See THIRD_PARTY_NOTICES.md.
 */

import {
  LAYER_LABEL_WEIGHTS,
  allocateLayerQuotas,
  normalizeAllocationStrategy,
  type AllocationStrategy,
} from "./labelQuota";

export interface ScreenRect {
  readonly x: number;
  readonly y: number;
  readonly w: number;
  readonly h: number;
}

export const LABEL_CELL_SIZE_PX = 32;
export const LABEL_COLLISION_PADDING_PX = 4;

export const LABEL_ARBITER_TIMING = Object.freeze({
  minimumLifetimeMs: 2500,
  cooldownMs: 1200,
});

/** Cell indices fold into ±8192 so a far-away rect cannot run a million-cell loop. */
const CELL_CLAMP = 8192;

export interface LabelCandidate {
  readonly key: string;
  readonly layerId: string;
  readonly rect: ScreenRect;
  readonly priority: number;
}

export interface SolveOptions {
  readonly capacity: number;
  readonly strategy?: AllocationStrategy;
  readonly layerWeights?: Readonly<Record<string, number>>;
  readonly now?: number;
}

export interface SolveDiagnostics {
  readonly capacity: number;
  readonly selected: number;
  readonly quotas: Readonly<Record<string, number>>;
  readonly droppedToCollision: number;
  readonly heldByLifetime: number;
  readonly blockedByCooldown: number;
  readonly lentSlots: number;
}

type AdmitResult = "placed" | "collision" | "cooldown";

interface LabelState {
  selectedAt: number;
  droppedAt: number | null;
}

interface RankedCandidate {
  candidate: LabelCandidate;
  rank: number;
}

interface HashBucket {
  generation: number;
  rects: ScreenRect[];
}

function isFiniteRect(rect: ScreenRect): boolean {
  return (
    Number.isFinite(rect.x) &&
    Number.isFinite(rect.y) &&
    Number.isFinite(rect.w) &&
    Number.isFinite(rect.h) &&
    rect.w > 0 &&
    rect.h > 0
  );
}

function clampCell(index: number): number {
  if (index <= -CELL_CLAMP) return -CELL_CLAMP;
  if (index >= CELL_CLAMP) return CELL_CLAMP;
  return index;
}

function compareKey(a: string, b: string): number {
  return a < b ? -1 : a > b ? 1 : 0;
}

function sumQuotas(quotas: ReadonlyMap<string, number>): number {
  let total = 0;
  for (const value of quotas.values()) total += value;
  return total;
}

/**
 * Axis-aligned overlap with `padding` as a gutter (applied once, not doubled
 * onto both rects). Default 4 px: a 2 px gap collides, a 5 px gap does not.
 */
export function rectsOverlap(
  a: ScreenRect,
  b: ScreenRect,
  padding = LABEL_COLLISION_PADDING_PX,
): boolean {
  const gap = Number.isFinite(padding) ? padding : LABEL_COLLISION_PADDING_PX;
  return (
    a.x < b.x + b.w + gap &&
    a.x + a.w + gap > b.x &&
    a.y < b.y + b.h + gap &&
    a.y + a.h + gap > b.y
  );
}

export function estimateLabelRect(
  screenX: number,
  screenY: number,
  text: string,
  fontSizePx: number,
): ScreenRect {
  const w = Math.max(1, text.length) * fontSizePx * 0.6;
  const h = fontSizePx * 1.2;
  return { x: screenX - w / 2, y: screenY - h / 2, w, h };
}

/**
 * Uniform 32 px grid. Buckets persist; a generation stamp invalidates them
 * instead of allocating a new Map each solve.
 */
export class LabelSpatialHash {
  private generation = 1;
  private readonly cells = new Map<string, HashBucket>();

  clear(): void {
    this.generation += 1;
    if (this.generation >= Number.MAX_SAFE_INTEGER) {
      this.cells.clear();
      this.generation = 1;
    }
  }

  insert(rect: ScreenRect): void {
    if (!isFiniteRect(rect)) return;
    this.forEachCell(rect, (key) => {
      let bucket = this.cells.get(key);
      if (!bucket) {
        bucket = { generation: this.generation, rects: [] };
        this.cells.set(key, bucket);
      } else if (bucket.generation !== this.generation) {
        bucket.generation = this.generation;
        bucket.rects.length = 0;
      }
      bucket.rects.push(rect);
    });
  }

  collides(rect: ScreenRect): boolean {
    if (!isFiniteRect(rect)) return false;
    let hit = false;
    this.forEachCell(rect, (key) => {
      if (hit) return;
      const bucket = this.cells.get(key);
      if (!bucket || bucket.generation !== this.generation) return;
      for (const other of bucket.rects) {
        if (rectsOverlap(rect, other)) {
          hit = true;
          return;
        }
      }
    });
    return hit;
  }

  private forEachCell(rect: ScreenRect, visit: (key: string) => void): void {
    const size = LABEL_CELL_SIZE_PX;
    const pad = LABEL_COLLISION_PADDING_PX;
    const minX = clampCell(Math.floor((rect.x - pad) / size));
    const maxX = clampCell(Math.floor((rect.x + rect.w + pad) / size));
    const minY = clampCell(Math.floor((rect.y - pad) / size));
    const maxY = clampCell(Math.floor((rect.y + rect.h + pad) / size));
    for (let y = minY; y <= maxY; y++) {
      for (let x = minX; x <= maxX; x++) {
        visit(`${x},${y}`);
      }
    }
  }
}

/** Rank 0 is the layer's best. A singleton layer is 0; divisor is never 0. */
function normalise(candidates: readonly LabelCandidate[]): RankedCandidate[] {
  const buckets = new Map<string, LabelCandidate[]>();
  for (const candidate of candidates) {
    const list = buckets.get(candidate.layerId);
    if (list) list.push(candidate);
    else buckets.set(candidate.layerId, [candidate]);
  }

  const ranked: RankedCandidate[] = [];
  for (const list of buckets.values()) {
    list.sort((a, b) => {
      if (a.priority !== b.priority) return b.priority > a.priority ? 1 : -1;
      return compareKey(a.key, b.key);
    });
    const denom = Math.max(1, list.length - 1);
    for (let i = 0; i < list.length; i++) {
      const item = list[i];
      if (!item) continue;
      ranked.push({ candidate: item, rank: i / denom });
    }
  }
  return ranked;
}

export class LabelArbiter {
  private readonly states = new Map<string, LabelState>();
  private selected = new Set<string>();
  private lastDiagnostics: SolveDiagnostics | null = null;
  private readonly spatial = new LabelSpatialHash();

  solve(candidates: readonly LabelCandidate[], options: SolveOptions): ReadonlySet<string> {
    const providedNow = options.now;
    const now =
      providedNow !== undefined && Number.isFinite(providedNow) ? providedNow : Date.now();

    const offered = new Set<string>();
    for (const candidate of candidates) offered.add(candidate.key);
    for (const key of [...this.states.keys()]) {
      if (!offered.has(key)) this.states.delete(key);
    }
    const liveSelected = new Set<string>();
    for (const key of this.selected) {
      if (offered.has(key)) liveSelected.add(key);
    }
    this.selected = liveSelected;

    const demand = new Map<string, number>();
    for (const candidate of candidates) {
      demand.set(candidate.layerId, (demand.get(candidate.layerId) ?? 0) + 1);
    }
    const strategy = normalizeAllocationStrategy(options.strategy);
    const quotas = allocateLayerQuotas(
      demand,
      options.capacity,
      strategy,
      options.layerWeights ?? LAYER_LABEL_WEIGHTS,
    );
    const capacity = sumQuotas(quotas);

    const held = new Set<string>();
    for (const key of this.selected) {
      const state = this.states.get(key);
      if (state === undefined) continue;
      if (now - state.selectedAt < LABEL_ARBITER_TIMING.minimumLifetimeMs) {
        held.add(key);
      }
    }

    const order = normalise(candidates);
    order.sort((a, b) => {
      const aHeld = held.has(a.candidate.key) ? 0 : 1;
      const bHeld = held.has(b.candidate.key) ? 0 : 1;
      if (aHeld !== bHeld) return aHeld - bHeld;
      if (a.rank !== b.rank) return a.rank - b.rank;
      return compareKey(a.candidate.key, b.candidate.key);
    });

    this.spatial.clear();
    const remainingQuota = new Map(quotas);
    const nextSelected = new Set<string>();
    const deferred: RankedCandidate[] = [];
    let placed = 0;
    let droppedToCollision = 0;
    let blockedByCooldown = 0;
    let lentSlots = 0;

    const admit = (candidate: LabelCandidate): AdmitResult => {
      const state = this.states.get(candidate.key);
      const cooling =
        !held.has(candidate.key) &&
        state !== undefined &&
        state.droppedAt !== null &&
        now - state.droppedAt < LABEL_ARBITER_TIMING.cooldownMs;
      if (cooling) return "cooldown";
      if (!isFiniteRect(candidate.rect) || this.spatial.collides(candidate.rect)) {
        return "collision";
      }
      this.spatial.insert(candidate.rect);
      nextSelected.add(candidate.key);
      placed += 1;
      return "placed";
    };

    const tally = (result: AdmitResult): void => {
      if (result === "collision") droppedToCollision += 1;
      else if (result === "cooldown") blockedByCooldown += 1;
    };

    for (const item of order) {
      const remaining = remainingQuota.get(item.candidate.layerId) ?? 0;
      if (remaining <= 0) {
        deferred.push(item);
        continue;
      }
      const result = admit(item.candidate);
      if (result === "placed") {
        remainingQuota.set(item.candidate.layerId, remaining - 1);
      } else {
        tally(result);
      }
    }

    if (placed < capacity) {
      for (const item of deferred) {
        if (placed >= capacity) break;
        const result = admit(item.candidate);
        if (result === "placed") lentSlots += 1;
        else tally(result);
      }
    }

    for (const key of nextSelected) {
      const prev = this.states.get(key);
      if (prev && this.selected.has(key)) {
        prev.droppedAt = null;
      } else if (prev) {
        prev.selectedAt = now;
        prev.droppedAt = null;
      } else {
        this.states.set(key, { selectedAt: now, droppedAt: null });
      }
    }
    for (const key of this.selected) {
      if (nextSelected.has(key)) continue;
      const prev = this.states.get(key);
      if (prev) prev.droppedAt = now;
    }

    let heldByLifetime = 0;
    for (const key of nextSelected) {
      if (held.has(key)) heldByLifetime += 1;
    }

    const quotaRecord: Record<string, number> = {};
    for (const [layerId, value] of quotas) quotaRecord[layerId] = value;

    this.selected = nextSelected;
    this.lastDiagnostics = {
      capacity,
      selected: nextSelected.size,
      quotas: quotaRecord,
      droppedToCollision,
      heldByLifetime,
      blockedByCooldown,
      lentSlots,
    };
    return this.selected;
  }

  isSelected(key: string): boolean {
    return this.selected.has(key);
  }

  diagnostics(): SolveDiagnostics | null {
    return this.lastDiagnostics;
  }

  clear(): void {
    this.states.clear();
    this.selected = new Set();
    this.lastDiagnostics = null;
    this.spatial.clear();
  }
}
