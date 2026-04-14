/**
 * Minimal EventSource mock for vitest/jsdom.
 *
 * Registered by installing on globalThis — the production `useSignalFeed`
 * hook references `window.EventSource` / `globalThis.EventSource` directly,
 * so this mock replaces the real class during tests.
 *
 * Design goals:
 *  - Spec-ish surface: `onopen`, `onerror`, `onmessage`, `addEventListener`,
 *    `close`, `readyState`, `url`.
 *  - Per-instance `.trigger(event, data, id?)` helper for tests to push a
 *    frame through named-event listeners (and `onmessage` for the default
 *    `"message"` type).
 *  - Class-level registry (`MockEventSource.instances`) so tests can inspect
 *    reconnections (new instances are created per reconnect).
 *  - `readyState` follows the WHATWG values: 0 CONNECTING, 1 OPEN, 2 CLOSED.
 *  - `open()` transitions 0 → 1 and fires `onopen`.
 *  - Each instance captures the `lastEventIdHint` passed via query param so
 *    tests can assert the hook threads `last_event_id` through reconnects.
 */

type Listener = (ev: MessageEventLike) => void;

export interface MessageEventLike {
  data: string;
  lastEventId: string;
  type: string;
}

export class MockEventSource {
  static instances: MockEventSource[] = [];
  static reset() {
    MockEventSource.instances = [];
  }

  readonly url: string;
  readonly lastEventIdHint: string | null;
  readyState = 0;

  onopen: ((ev: Event) => void) | null = null;
  onerror: ((ev: Event) => void) | null = null;
  onmessage: ((ev: MessageEventLike) => void) | null = null;

  private listeners: Map<string, Set<Listener>> = new Map();

  constructor(url: string) {
    this.url = url;
    // Extract `last_event_id` query param if present — used by the hook's
    // fallback reconnection strategy.
    try {
      const parsed = new URL(url, "http://localhost");
      this.lastEventIdHint = parsed.searchParams.get("last_event_id");
    } catch {
      this.lastEventIdHint = null;
    }
    MockEventSource.instances.push(this);
  }

  addEventListener(event: string, listener: Listener) {
    let set = this.listeners.get(event);
    if (!set) {
      set = new Set();
      this.listeners.set(event, set);
    }
    set.add(listener);
  }

  removeEventListener(event: string, listener: Listener) {
    this.listeners.get(event)?.delete(listener);
  }

  close() {
    this.readyState = 2;
  }

  // ── Test helpers ──────────────────────────────────────────────────────

  /** Transition to OPEN and fire onopen handlers. */
  open() {
    this.readyState = 1;
    this.onopen?.(new Event("open"));
  }

  /** Fire an `error` event; hook is expected to close and reconnect. */
  fail() {
    this.onerror?.(new Event("error"));
  }

  /** Deliver a named SSE frame. Use `"message"` for default / unnamed. */
  trigger(event: string, data: string, id = "") {
    const payload: MessageEventLike = { data, lastEventId: id, type: event };
    if (event === "message" && this.onmessage) {
      this.onmessage(payload);
    }
    const set = this.listeners.get(event);
    if (set) {
      for (const cb of set) cb(payload);
    }
  }
}

export function installMockEventSource() {
  MockEventSource.reset();
  (globalThis as unknown as { EventSource: typeof MockEventSource }).EventSource =
    MockEventSource;
}

export function uninstallMockEventSource() {
  // Leaving the class installed is harmless between tests, but clear the
  // instance list so assertions don't leak across tests.
  MockEventSource.reset();
}
