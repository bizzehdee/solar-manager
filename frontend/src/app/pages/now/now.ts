import { Component, OnInit, computed, inject, signal } from '@angular/core';
import { DatePipe } from '@angular/common';

import { ApiService } from '../../core/api.service';
import { DashboardDataService } from '../../core/dashboard-data.service';
import { DashboardConfig, DeviceClock } from '../../core/models';
import { DashboardHost } from '../../shared/dashboard-host';

// "Now" view (plan.md §8): the live energy snapshot, now driven by the L06 dashboard system (T_DB4).
// The configurable grid (energy-flow + gauges + cards) is rendered by <app-dashboard-host> from the
// "now" built-in layout; this page keeps the device chrome that isn't (yet) a widget — the fault
// banner, run-state badge, inverter clock drift, and battery-health panel. Live data comes from
// DashboardDataService (the shared WebSocket-backed source).
@Component({
  selector: 'app-now',
  imports: [DashboardHost, DatePipe],
  template: `
    <div class="d-flex align-items-center justify-content-between mb-3">
      <h4 class="mb-0 d-flex align-items-center gap-2">
        Now
        @if (runState(); as rs) {
          <span class="badge text-bg-secondary text-capitalize">{{ rs }}</span>
        }
      </h4>
      @if (dashboard()) {
        <button class="btn btn-sm btn-outline-secondary" (click)="reset()" title="Reset to the default layout">
          <i class="bi bi-arrow-counterclockwise"></i> Reset to default
        </button>
      }
    </div>

    <!-- Fault banner (T054): prominent only when the inverter reports active fault codes. -->
    @if (faultCodes().length > 0) {
      <div class="alert alert-danger d-flex align-items-center" role="alert">
        <i class="bi bi-exclamation-triangle-fill me-2"></i>
        <span>Inverter faults: {{ faultCodes().join(', ') }}</span>
      </div>
    }

    @if (dashboard(); as d) {
      <app-dashboard-host [dashboard]="d" [data]="data.data()" (layoutSaved)="onSaved(d, $event)" />
    } @else {
      <div class="text-secondary"><span class="spinner-border spinner-border-sm"></span> Loading dashboard…</div>
    }

    @if (metrics()) {
      <!-- Inverter clock drift (T097): shown when the device exposes an RTC; Sync gated. -->
      @if (clock(); as c) {
        @if (c.supported) {
          <div class="card mt-3">
            <div class="card-body d-flex align-items-center justify-content-between flex-wrap gap-2 py-2">
              <div class="small">
                <span class="fw-semibold"><i class="bi bi-clock-history"></i> Inverter clock</span>
                <span class="text-secondary ms-2">
                  {{ c.device_time ? (c.device_time | date: 'MMM d, HH:mm:ss') : '—' }} · drift {{ driftLabel(c) }}
                </span>
              </div>
              @if (c.syncable) {
                <button class="btn btn-sm btn-outline-primary" [disabled]="syncingClock()" (click)="syncClock()">
                  <i class="bi bi-arrow-repeat"></i> Sync to system time
                </button>
              } @else {
                <span class="badge text-bg-light">read-only</span>
              }
            </div>
          </div>
        }
      }
    }
  `,
})
export class NowPage implements OnInit {
  protected readonly data = inject(DashboardDataService);
  private readonly api = inject(ApiService);

  /** The "now" built-in dashboard layout, loaded from the API. */
  readonly dashboard = signal<DashboardConfig | null>(null);

  // Chrome (faults / run-state) reads live data from the shared service. Battery-health stats are
  // now metric-card widgets in the Now layout, not a bespoke panel.
  readonly metrics = this.data.metrics;
  readonly faultCodes = this.data.faultCodes;
  readonly runState = computed(() => this.data.runState()?.replace(/_/g, ' '));

  // Inverter clock drift (T097), polled with the device fetch.
  readonly clock = signal<DeviceClock | null>(null);
  readonly syncingClock = signal(false);
  private deviceId: string | null = null;

  ngOnInit(): void {
    this.loadDashboard();
    this.api.getDevices().subscribe((res) => {
      const dev = res.devices[0];
      if (dev?.id) {
        this.deviceId = dev.id;
        this.api.getDeviceClock(dev.id).subscribe({ next: (c) => this.clock.set(c), error: () => {} });
      }
    });
  }

  private loadDashboard(): void {
    this.api.getDashboard('now').subscribe({ next: (d) => this.dashboard.set(d), error: () => {} });
  }

  /** Persist an edited layout as a personalised override of the built-in. */
  onSaved(d: DashboardConfig, widgets: DashboardConfig['widgets']): void {
    this.api.putDashboard('now', { name: d.name, widgets }).subscribe({ next: (saved) => this.dashboard.set(saved) });
  }

  /** Restore the built-in's default layout (drops any personalised override, then reloads). */
  reset(): void {
    this.api.deleteDashboard('now').subscribe({ next: () => this.loadDashboard() });
  }

  /** Human drift: "in sync" under 1 s, else signed seconds (or minutes when large). */
  driftLabel(c: DeviceClock): string {
    const d = c.drift_s;
    if (d === null) return '—';
    if (Math.abs(d) < 1) return 'in sync';
    const sign = d > 0 ? '+' : '−';
    const abs = Math.abs(d);
    return abs >= 120 ? `${sign}${Math.round(abs / 60)} min` : `${sign}${Math.round(abs)} s`;
  }

  syncClock(): void {
    if (!this.deviceId) return;
    this.syncingClock.set(true);
    this.api.syncDeviceClock(this.deviceId).subscribe({
      next: () =>
        this.api.getDeviceClock(this.deviceId!).subscribe({
          next: (c) => (this.clock.set(c), this.syncingClock.set(false)),
          error: () => this.syncingClock.set(false),
        }),
      error: () => this.syncingClock.set(false),
    });
  }
}
