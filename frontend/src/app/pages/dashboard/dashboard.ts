import { Component, OnDestroy, OnInit, inject, signal } from '@angular/core';
import { ActivatedRoute } from '@angular/router';
import { Subscription } from 'rxjs';

import { ApiService } from '../../core/api.service';
import { DashboardDataService } from '../../core/dashboard-data.service';
import { DashboardConfig } from '../../core/models';
import { DashboardHost } from '../../shared/dashboard-host';

// Generic user-dashboard page (L06 / T_DB6): renders any dashboard by id from the route
// (`/dashboard/:id`) through the shared host, fed by the live data service. The Now/History
// built-ins keep their own dedicated pages (extra chrome); this is the route for user dashboards.
@Component({
  selector: 'app-dashboard',
  imports: [DashboardHost],
  template: `
    @if (dashboard(); as d) {
      <app-dashboard-host [dashboard]="d" [data]="data.data()" (layoutSaved)="onSaved(d, $event)">
        <h4 dashTitle class="mb-0">{{ d.name }}</h4>
      </app-dashboard-host>
    } @else if (notFound()) {
      <div class="alert alert-warning">That dashboard doesn't exist.</div>
    } @else {
      <div class="text-secondary"><span class="spinner-border spinner-border-sm"></span> Loading dashboard…</div>
    }
  `,
})
export class DashboardPage implements OnInit, OnDestroy {
  protected readonly data = inject(DashboardDataService);
  private readonly api = inject(ApiService);
  private readonly route = inject(ActivatedRoute);

  readonly dashboard = signal<DashboardConfig | null>(null);
  readonly notFound = signal(false);
  private sub?: Subscription;

  ngOnInit(): void {
    // React to id changes so switching between user dashboards reuses the component.
    this.sub = this.route.paramMap.subscribe((params) => this.load(params.get('id')));
  }

  ngOnDestroy(): void {
    this.sub?.unsubscribe();
  }

  private load(id: string | null): void {
    this.dashboard.set(null);
    this.notFound.set(false);
    if (!id) {
      this.notFound.set(true);
      return;
    }
    this.api.getDashboard(id).subscribe({
      next: (d) => this.dashboard.set(d),
      error: () => this.notFound.set(true),
    });
  }

  /** Persist an edited layout for this user dashboard. */
  onSaved(d: DashboardConfig, widgets: DashboardConfig['widgets']): void {
    this.api.putDashboard(d.id, { name: d.name, widgets }).subscribe({ next: (saved) => this.dashboard.set(saved) });
  }
}
