import { Component, OnInit, inject, signal } from '@angular/core';
import { DatePipe, DecimalPipe } from '@angular/common';

import { ApiService } from '../../core/api.service';
import { Diagnostics, GridEvent } from '../../core/models';

// Diagnostics (plan.md §19 / T092): a read-only operational snapshot — build/schema, DB
// size, rollup lag, active alerts, and per-device online + Modbus comms health.
@Component({
  selector: 'app-diagnostics',
  imports: [DecimalPipe, DatePipe],
  template: `
    <div class="d-flex align-items-center justify-content-between mb-3">
      <h4 class="mb-0"><i class="bi bi-clipboard-pulse"></i> Diagnostics</h4>
      <button class="btn btn-sm btn-outline-secondary" (click)="refresh()" [disabled]="loading()">
        <i class="bi bi-arrow-clockwise"></i> Refresh
      </button>
    </div>

    @if (loading()) {
      <div class="text-secondary"><span class="spinner-border spinner-border-sm"></span> Loading…</div>
    } @else if (diag(); as d) {
      <div class="row g-3 mb-3">
        <div class="col-6 col-md-3"><div class="card h-100"><div class="card-body">
          <div class="small text-secondary">Version</div><div class="fs-5 fw-semibold">{{ d.version }}</div>
        </div></div></div>
        <div class="col-6 col-md-3"><div class="card h-100"><div class="card-body">
          <div class="small text-secondary">DB schema</div><div class="fs-5 fw-semibold">v{{ d.schema_version }}</div>
        </div></div></div>
        <div class="col-6 col-md-3"><div class="card h-100"><div class="card-body">
          <div class="small text-secondary">Database size</div>
          <div class="fs-5 fw-semibold">{{ d.database.size_bytes === null ? '—' : humanBytes(d.database.size_bytes) }}</div>
        </div></div></div>
        <div class="col-6 col-md-3"><div class="card h-100"><div class="card-body">
          <div class="small text-secondary">Rollup lag</div>
          <div class="fs-5 fw-semibold">{{ d.rollup.lag_s === null ? '—' : (d.rollup.lag_s | number: '1.0-0') + ' s' }}</div>
        </div></div></div>
      </div>

      <div class="card mb-3"><div class="card-body py-2 small text-secondary d-flex flex-wrap gap-3">
        <span>Poll interval: <strong>{{ d.poll_interval_s }} s</strong></span>
        <span>Control: <strong>{{ d.control_enabled ? 'enabled' : 'disabled' }}</strong></span>
        <span>Active alerts: <strong>{{ d.alerts.active_count }}</strong></span>
        <span>DB path: <code>{{ d.database.path }}</code></span>
      </div></div>

      <!-- Host network link (IP, status, Wi-Fi SSID/signal or Ethernet name/link speed). -->
      @if (d.network; as net) {
        <div class="card mb-3">
          <div class="card-header d-flex align-items-center gap-2">
            <i class="bi {{ net.type === 'wifi' ? 'bi-wifi' : net.type === 'ethernet' ? 'bi-ethernet' : 'bi-hdd-network' }}"></i>
            Host network
            @if (net.status) { <span class="badge text-bg-{{ isUp(net.status) ? 'success' : 'secondary' }} ms-auto text-capitalize">{{ net.status }}</span> }
          </div>
          <div class="card-body small d-flex flex-wrap gap-4">
            <span>IP address: <strong>{{ net.ip || '—' }}</strong></span>
            <span>Interface: <strong>{{ net.interface || '—' }}</strong> <span class="text-secondary">({{ net.type }})</span></span>
            @if (net.wifi; as w) {
              <span>SSID: <strong>{{ w.ssid || '—' }}</strong></span>
              <span>Signal:
                <strong>{{ w.signal_pct === null ? '—' : w.signal_pct + '%' }}</strong>
                @if (w.signal_dbm !== null) { <span class="text-secondary">({{ w.signal_dbm }} dBm)</span> }
              </span>
            }
            @if (net.ethernet; as e) {
              <span>Link: <strong>{{ e.name || '—' }}</strong></span>
              <span>Speed: <strong>{{ e.link_speed_mbps === null ? '—' : e.link_speed_mbps + ' Mbps' }}</strong></span>
            }
          </div>
        </div>
      }

      <div class="card">
        <div class="card-header"><i class="bi bi-hdd-network"></i> Devices</div>
        <div class="table-responsive">
          <table class="table table-sm align-middle mb-0">
            <thead>
              <tr><th>Device</th><th>Status</th><th>Last sample</th><th>Clock</th><th class="text-end">Comms (tx / fail / retry)</th><th>Last error</th></tr>
            </thead>
            <tbody>
              @for (dev of d.devices; track dev.device_id) {
                <tr>
                  <td><div class="fw-semibold">{{ dev.device_id }}</div><div class="small text-secondary">{{ dev.vendor }} {{ dev.model }}</div></td>
                  <td><span class="badge text-bg-{{ dev.online ? 'success' : 'danger' }}">{{ dev.online ? 'online' : 'offline' }}</span></td>
                  <td>{{ dev.last_sample_age_s === null ? '—' : (dev.last_sample_age_s | number: '1.0-0') + ' s ago' }}</td>
                  <!-- Inverter clock drift + sync (T097), per device. -->
                  <td class="small">
                    @if (dev.clock?.supported) {
                      <span [class.text-warning]="driftWarn(dev.clock!.drift_s)">{{ driftLabel(dev.clock!.drift_s) }}</span>
                      @if (dev.clock!.syncable) {
                        <button class="btn btn-link btn-sm p-0 ms-2 align-baseline" [disabled]="syncing() === dev.device_id"
                                (click)="syncClock(dev.device_id)">
                          <i class="bi bi-arrow-repeat"></i> Sync
                        </button>
                      }
                    } @else { <span class="text-secondary">—</span> }
                  </td>
                  <td class="text-end">
                    @if (dev.comms) {
                      {{ dev.comms['transactions'] }} / {{ dev.comms['failures'] }} / {{ dev.comms['retries'] }}
                      @if (dev.comms['last_rtt_ms'] !== null) { <span class="text-secondary">· {{ dev.comms['last_rtt_ms'] }} ms</span> }
                    } @else { <span class="text-secondary">— (no wire)</span> }
                  </td>
                  <td class="small text-danger">{{ dev.comms?.['last_error'] || '' }}</td>
                </tr>
              }
            </tbody>
          </table>
        </div>
      </div>
    } @else {
      <div class="alert alert-secondary mb-0">Diagnostics unavailable.</div>
    }

    <!-- Grid-outage timeline (T095). -->
    <div class="card mt-3">
      <div class="card-header"><i class="bi bi-plug"></i> Grid events</div>
      @if (gridEvents().length === 0) {
        <div class="card-body py-2 small text-secondary">No grid loss/return events recorded.</div>
      } @else {
        <ul class="list-group list-group-flush">
          @for (e of gridEvents(); track $index) {
            <li class="list-group-item d-flex justify-content-between align-items-center py-2 small">
              <span>
                <span class="badge text-bg-{{ e.event === 'outage_start' ? 'danger' : 'success' }} me-2">
                  {{ e.event === 'outage_start' ? 'grid lost' : 'grid restored' }}
                </span>
                {{ e.device_id }}
              </span>
              <span class="text-secondary">{{ e.ts * 1000 | date: 'MMM d, HH:mm:ss' }}</span>
            </li>
          }
        </ul>
      }
    </div>
  `,
})
export class DiagnosticsPage implements OnInit {
  private readonly api = inject(ApiService);
  readonly diag = signal<Diagnostics | null>(null);
  readonly gridEvents = signal<GridEvent[]>([]);
  readonly loading = signal(true);
  readonly syncing = signal<string | null>(null); // device id mid-sync

  ngOnInit(): void {
    this.refresh();
  }

  /** Human drift: "in sync" under 1 s, else signed seconds (or minutes when large). */
  driftLabel(drift: number | null): string {
    if (drift === null) return '—';
    if (Math.abs(drift) < 1) return 'in sync';
    const sign = drift > 0 ? '+' : '−';
    const abs = Math.abs(drift);
    return abs >= 120 ? `${sign}${Math.round(abs / 60)} min` : `${sign}${Math.round(abs)} s`;
  }

  /** Flag a clock that's drifted enough to be worth correcting (≥ 1 minute). */
  driftWarn(drift: number | null): boolean {
    return drift !== null && Math.abs(drift) >= 60;
  }

  /** Correct an inverter's clock to system time, then reload the snapshot. */
  syncClock(deviceId: string): void {
    this.syncing.set(deviceId);
    this.api.syncDeviceClock(deviceId).subscribe({
      next: () => (this.syncing.set(null), this.refresh()),
      error: () => this.syncing.set(null),
    });
  }

  refresh(): void {
    this.loading.set(true);
    this.api.getDiagnostics().subscribe({
      next: (d) => (this.diag.set(d), this.loading.set(false)),
      error: () => (this.diag.set(null), this.loading.set(false)),
    });
    this.api.getGridEvents().subscribe({ next: (r) => this.gridEvents.set(r.events), error: () => {} });
  }

  /** Treat "up"/"connected" operstates as a healthy (green) link. */
  isUp(status: string): boolean {
    return status === 'up' || status === 'connected';
  }

  /** Bytes → human (KB/MB/GB). */
  humanBytes(n: number): string {
    if (n < 1024) return `${n} B`;
    const units = ['KB', 'MB', 'GB'];
    let v = n / 1024;
    let i = 0;
    while (v >= 1024 && i < units.length - 1) {
      v /= 1024;
      i++;
    }
    return `${v.toFixed(1)} ${units[i]}`;
  }
}
