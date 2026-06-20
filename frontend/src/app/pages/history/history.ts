import { Component, OnInit, inject, signal } from '@angular/core';

import { ApiService } from '../../core/api.service';
import { DashboardConfig } from '../../core/models';
import { DashboardHost } from '../../shared/dashboard-host';

// History view (plan.md §9), now driven by the L06 dashboard system (T_DB5): the "history" built-in
// lays out the daily-KPI row + the interactive metric/resolution/range time-series chart as widgets.
// This page is a thin host container; the widgets fetch their own data.
@Component({
  selector: 'app-history',
  imports: [DashboardHost],
  template: `
    <div class="d-flex align-items-center justify-content-between mb-3">
      <h4 class="mb-0"><i class="bi bi-graph-up"></i> History</h4>
      @if (dashboard()) {
        <button class="btn btn-sm btn-outline-secondary" (click)="reset()" title="Reset to the default layout">
          <i class="bi bi-arrow-counterclockwise"></i> Reset to default
        </button>
      }
    </div>

    @if (dashboard(); as d) {
      <app-dashboard-host [dashboard]="d" />
    } @else {
      <div class="text-secondary"><span class="spinner-border spinner-border-sm"></span> Loading dashboard…</div>
    }
  `,
})
export class HistoryPage implements OnInit {
  private readonly api = inject(ApiService);

  /** The "history" built-in dashboard layout, loaded from the API. */
  readonly dashboard = signal<DashboardConfig | null>(null);

  ngOnInit(): void {
    this.loadDashboard();
  }

  private loadDashboard(): void {
    this.api.getDashboard('history').subscribe({ next: (d) => this.dashboard.set(d), error: () => {} });
  }

  /** Restore the built-in's default layout (re-fetches the server-seeded config). */
  reset(): void {
    this.loadDashboard();
  }
}
