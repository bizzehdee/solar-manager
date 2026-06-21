import { DestroyRef, Injectable, inject, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';

import { ApiService } from './api.service';
import { ConnStatus, Snapshot } from './models';

// Live data path (plan.md §8): pushes each new Reading over a WebSocket; if the socket
// drops, the status goes amber and the client falls back to polling /api/live, while
// periodically trying to reconnect. Exposed as signals so components stay zoneless-safe.
@Injectable({ providedIn: 'root' })
export class LiveService {
  private api = inject(ApiService);
  private readonly destroyRef = inject(DestroyRef);

  readonly snapshot = signal<Snapshot | null>(null);
  readonly status = signal<ConnStatus>('connecting');

  private ws?: WebSocket;
  private pollTimer?: ReturnType<typeof setInterval>;
  private reconnectTimer?: ReturnType<typeof setTimeout>;
  private started = false;
  private destroyed = false;

  constructor() {
    // Tear down on injector destruction (incl. each TestBed teardown — this is a root service), so a
    // polling/reconnect timer never fires an HTTP request into a destroyed injection context (NG0205).
    this.destroyRef.onDestroy(() => {
      this.destroyed = true;
      this.stopPolling();
      if (this.reconnectTimer) {
        clearTimeout(this.reconnectTimer);
        this.reconnectTimer = undefined;
      }
      this.ws?.close();
    });
  }

  /** Idempotent — safe to call from multiple components. */
  start(): void {
    if (this.started) return;
    this.started = true;
    this.connect();
  }

  private connect(): void {
    try {
      this.ws = new WebSocket(this.wsUrl());
    } catch {
      this.fallback();
      return;
    }
    this.ws.onopen = () => {
      this.status.set('live');
      this.stopPolling();
    };
    this.ws.onmessage = (e) => {
      try {
        this.snapshot.set(JSON.parse(e.data) as Snapshot);
      } catch {
        /* ignore malformed frame */
      }
    };
    this.ws.onerror = () => this.ws?.close();
    this.ws.onclose = () => this.fallback();
  }

  private fallback(): void {
    this.status.set('polling');
    this.startPolling();
    this.scheduleReconnect();
  }

  private startPolling(): void {
    if (this.pollTimer || this.destroyed) return;
    const poll = () => {
      if (this.destroyed) return;
      this.api
        .getLive()
        .pipe(takeUntilDestroyed(this.destroyRef))
        .subscribe({ next: (s) => this.snapshot.set(s) });
    };
    poll();
    this.pollTimer = setInterval(poll, 3000);
  }

  private stopPolling(): void {
    if (this.pollTimer) {
      clearInterval(this.pollTimer);
      this.pollTimer = undefined;
    }
  }

  private scheduleReconnect(): void {
    if (this.reconnectTimer) return;
    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = undefined;
      this.connect();
    }, 5000);
  }

  private wsUrl(): string {
    const proto = location.protocol === 'https:' ? 'wss' : 'ws';
    return `${proto}://${location.host}/ws/live`;
  }
}
