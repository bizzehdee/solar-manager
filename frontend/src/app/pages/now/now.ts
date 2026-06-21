import { Component, OnInit, computed, inject, signal } from '@angular/core';

import { ApiService } from '../../core/api.service';
import { DashboardDataService } from '../../core/dashboard-data.service';
import { DashboardConfig } from '../../core/models';
import { DashboardHost } from '../../shared/dashboard-host';

// "Now" view (plan.md §8): the live energy snapshot, now driven by the L06 dashboard system (T_DB4).
// The configurable grid (energy-flow + gauges + cards) is rendered by <app-dashboard-host> from the
// "now" built-in layout; this page keeps the device chrome that isn't a widget — the fault banner and
// run-state badge. (Inverter clock drift lives in Settings › Diagnostics, where per-device health is.)
// Live data comes from DashboardDataService (the shared WebSocket-backed source).
@Component({
  selector: 'app-now',
  imports: [DashboardHost],
  template: `
    <!-- Fault banner (T054): prominent only when the inverter reports active fault codes. -->
    @if (faultCodes().length > 0) {
      <div class="alert alert-danger d-flex align-items-center" role="alert">
        <i class="bi bi-exclamation-triangle-fill me-2"></i>
        <span>Inverter faults: {{ faultCodes().join(', ') }}</span>
      </div>
    }

    @if (dashboard(); as d) {
      <app-dashboard-host [dashboard]="d" [data]="data.data()" [canReset]="true"
                          (reset)="reset()" (layoutSaved)="onSaved(d, $event)">
        <h4 dashTitle class="mb-0 d-flex align-items-center gap-2">
          Now
          @if (runState(); as rs) {
            <span class="badge text-bg-secondary text-capitalize">{{ rs }}</span>
          }
        </h4>
      </app-dashboard-host>
    } @else {
      <div class="text-secondary"><span class="spinner-border spinner-border-sm"></span> Loading dashboard…</div>
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
  readonly faultCodes = this.data.faultCodes;
  readonly runState = computed(() => this.data.runState()?.replace(/_/g, ' '));

  ngOnInit(): void {
    this.loadDashboard();
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
}
