/**
 * WebSocket connection manager with auto-reconnect.
 */

type MessageHandler<T> = (data: T) => void;

interface WSMessage<T> {
  type: string;
  data: T;
  count: number;
}

export class WebSocketManager<T> {
  private ws: WebSocket | null = null;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private readonly reconnectDelay = 5000;
  private shouldReconnect = true;

  constructor(
    private readonly url: string,
    private readonly onMessage: MessageHandler<T[]>,
    private readonly onStatusChange?: (connected: boolean) => void,
  ) {}

  connect(): void {
    if (this.ws?.readyState === WebSocket.OPEN) return;

    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    const fullUrl = `${protocol}//${window.location.host}${this.url}`;

    this.ws = new WebSocket(fullUrl);

    this.ws.onopen = () => {
      this.onStatusChange?.(true);
    };

    this.ws.onmessage = (event: MessageEvent) => {
      try {
        const msg = JSON.parse(event.data as string) as WSMessage<T>;
        if (msg.data && Array.isArray(msg.data)) {
          this.onMessage(msg.data);
        }
      } catch {
        // skip malformed messages
      }
    };

    this.ws.onclose = () => {
      this.onStatusChange?.(false);
      if (this.shouldReconnect) {
        this.reconnectTimer = setTimeout(() => this.connect(), this.reconnectDelay);
      }
    };

    this.ws.onerror = () => {
      this.ws?.close();
    };
  }

  disconnect(): void {
    this.shouldReconnect = false;
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
    }
    this.ws?.close();
    this.ws = null;
  }
}
