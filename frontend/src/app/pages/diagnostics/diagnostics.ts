import { Component, OnInit, inject, signal } from '@angular/core';
import { DecimalPipe } from '@angular/common';

import { ApiService } from '../../core/api.service';
import { Diagnostics } from '../../core/models';

// Diagnostics (plan.md §19 / T092): a read-only operational snapshot — build/schema, DB
// size, rollup lag, active alerts, and per-device online + Modbus comms health.
@Component({
  selector: 'app-diagnostics',
  imports: [DecimalPipe],
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

      <div class="card">
        <div class="card-header"><i class="bi bi-hdd-network"></i> Devices</div>
        <div class="table-responsive">
          <table class="table table-sm align-middle mb-0">
            <thead>
              <tr><th>Device</th><th>Status</th><th>Last sample</th><th class="text-end">Comms (tx / fail / retry)</th><th>Last error</th></tr>
            </thead>
            <tbody>
              @for (dev of d.devices; track dev.device_id) {
                <tr>
                  <td><div class="fw-semibold">{{ dev.device_id }}</div><div class="small text-secondary">{{ dev.vendor }} {{ dev.model }}</div></td>
                  <td><span class="badge text-bg-{{ dev.online ? 'success' : 'danger' }}">{{ dev.online ? 'online' : 'offline' }}</span></td>
                  <td>{{ dev.last_sample_age_s === null ? '—' : (dev.last_sample_age_s | number: '1.0-0') + ' s ago' }}</td>
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
  `,
})
export class DiagnosticsPage implements OnInit {
  private readonly api = inject(ApiService);
  readonly diag = signal<Diagnostics | null>(null);
  readonly loading = signal(true);

  ngOnInit(): void {
    this.refresh();
  }

  refresh(): void {
    this.loading.set(true);
    this.api.getDiagnostics().subscribe({
      next: (d) => (this.diag.set(d), this.loading.set(false)),
      error: () => (this.diag.set(null), this.loading.set(false)),
    });
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
