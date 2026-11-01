/** Count delivered scene frames; scheduling callbacks are not rendered frames. */
export type DegradationLevel = 0 | 1 | 2 | 3 | 4;
export interface RenderSample { fps: number; degradation: DegradationLevel }

export class RenderBudget {
  private frames = 0;
  private lowSince: number | null = null;
  private highSince: number | null = null;
  private degradation: DegradationLevel = 0;
  constructor(private lastSample: number) {}

  frame(): void { this.frames += 1; }

  sample(now: number, evaluate: boolean): RenderSample {
    const elapsed = now - this.lastSample;
    const fps = elapsed > 0 ? this.frames * 1000 / elapsed : 0;
    this.frames = 0;
    this.lastSample = now;
    if (!evaluate || elapsed <= 0) {
      this.lowSince = this.highSince = null;
    } else if (fps < 30) {
      this.highSince = null;
      this.lowSince ??= now;
      if (now - this.lowSince >= 2000 && this.degradation < 4) {
        this.degradation = (this.degradation + 1) as DegradationLevel;
        this.lowSince = now;
      }
    } else {
      this.lowSince = null;
      this.highSince ??= now;
      if (now - this.highSince >= 5000 && this.degradation > 0) {
        this.degradation = (this.degradation - 1) as DegradationLevel;
        this.highSince = now;
      }
    }
    return { fps, degradation: this.degradation };
  }
}
