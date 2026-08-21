import type { SpatialContainmentPort } from "./contracts";

export type StrictPointLayerApplication<T> = Readonly<{
  readonly phase: "building" | "ready" | "unavailable";
  readonly stateRevision: number;
  readonly records: readonly T[];
  readonly inputCount: number;
  readonly includedCount: number;
  readonly excludedOutsideCount: number;
  readonly excludedBoundaryUncertainCount: number;
  readonly excludedInvalidCoordinateCount: number;
  readonly withheldCount: number;
}>;

export interface StrictPointLayerAdapter<T> {
  apply(records: readonly T[]): StrictPointLayerApplication<T>;
  subscribe(listener: () => void): () => void;
}

export interface CreateStrictPointLayerAdapterOptions<T> {
  readonly containment: SpatialContainmentPort;
  coordinates(record: T): readonly [longitude: number, latitude: number];
}

class StrictPointLayerAdapterImpl<T> implements StrictPointLayerAdapter<T> {
  constructor(
    private readonly containment: SpatialContainmentPort,
    private readonly coordinates: (
      record: T,
    ) => readonly [longitude: number, latitude: number],
  ) {}

  subscribe = (listener: () => void): (() => void) =>
    this.containment.subscribe(listener);

  apply(records: readonly T[]): StrictPointLayerApplication<T> {
    const snapshot = this.containment.getSnapshot();
    if (snapshot.phase !== "ready") {
      return Object.freeze({
        phase: snapshot.phase,
        stateRevision: snapshot.stateRevision,
        records: Object.freeze([]) as readonly T[],
        inputCount: records.length,
        includedCount: 0,
        excludedOutsideCount: 0,
        excludedBoundaryUncertainCount: 0,
        excludedInvalidCoordinateCount: 0,
        withheldCount: records.length,
      });
    }

    const included: T[] = [];
    let excludedOutsideCount = 0;
    let excludedBoundaryUncertainCount = 0;
    let excludedInvalidCoordinateCount = 0;
    for (const record of records) {
      try {
        const [longitude, latitude] = this.coordinates(record);
        const result = snapshot.contains(longitude, latitude);
        if (result === "inside") included.push(record);
        else if (result === "outside") excludedOutsideCount += 1;
        else excludedBoundaryUncertainCount += 1;
      } catch (error: unknown) {
        if (!(error instanceof RangeError)) throw error;
        excludedInvalidCoordinateCount += 1;
      }
    }

    return Object.freeze({
      phase: "ready",
      stateRevision: snapshot.stateRevision,
      records: Object.freeze(included),
      inputCount: records.length,
      includedCount: included.length,
      excludedOutsideCount,
      excludedBoundaryUncertainCount,
      excludedInvalidCoordinateCount,
      withheldCount: 0,
    });
  }
}

export function createStrictPointLayerAdapter<T>(
  options: CreateStrictPointLayerAdapterOptions<T>,
): StrictPointLayerAdapter<T> {
  return new StrictPointLayerAdapterImpl(
    options.containment,
    options.coordinates,
  );
}
