import { Component, OnInit, inject, signal } from '@angular/core';

import { ApiService } from '../../core/api.service';
import { DashboardDataService } from '../../core/dashboard-data.service';
import { DashboardConfig } from '../../core/models';
import { DashboardHost } from '../../shared/dashboard-host';

// History view (plan.md §9), now driven by the L06 dashboard system (T_DB5): the "history" built-in
// lays out the daily-KPI row + the interactive metric/resolution/range time-series chart as widgets.
// This page is a thin host container; the widgets fetch their own data.
@Component({
  selector: 'app-history',
  imports: [DashboardHost],
  template: `
    @if (dashboard(); as d) {
      <app-dashboard-host [dashboard]="d" [data]="data.data()" [canReset]="true"
                          (reset)="reset()" (layoutSaved)="onSaved(d, $event)">
        <h4 dashTitle class="mb-0"><i class="bi bi-graph-up"></i> History</h4>
      </app-dashboard-host>
    } @else {
      <div class="text-secondary"><span class="spinner-border spinner-border-sm"></span> Loading dashboard…</div>
    }
  `,
})
export class HistoryPage implements OnInit {
  private readonly api = inject(ApiService);
  protected readonly data = inject(DashboardDataService);

  /** The "history" built-in dashboard layout, loaded from the API. */
  readonly dashboard = signal<DashboardConfig | null>(null);

  ngOnInit(): void {
    this.loadDashboard();
  }

  private loadDashboard(): void {
    this.api.getDashboard('history').subscribe({ next: (d) => this.dashboard.set(d), error: () => {} });
  }

  /** Persist an edited layout as a personalised override of the built-in. */
  onSaved(d: DashboardConfig, widgets: DashboardConfig['widgets']): void {
    this.api.putDashboard('history', { name: d.name, widgets }).subscribe({ next: (saved) => this.dashboard.set(saved) });
  }

  /** Restore the built-in's default layout (drops any personalised override, then reloads). */
  reset(): void {
    this.api.deleteDashboard('history').subscribe({ next: () => this.loadDashboard() });
  }
}
