import { Component, OnInit, computed, inject, signal } from '@angular/core';
import { DatePipe } from '@angular/common';

import { ApiService } from '../../core/api.service';
import { Alert } from '../../core/models';

// Alerts inbox (plan.md §15 / T082): active + history with ack/snooze. Alerts are produced
// server-side by the rule engine; this view lists them, shows severity, and lets the user
// acknowledge or snooze. Read-only otherwise — rule editing is via the API (defaults shipped on).
@Component({
  selector: 'app-alerts',
  imports: [DatePipe],
  template: `
    <div class="d-flex align-items-center justify-content-between mb-3 flex-wrap gap-2">
      <h4 class="mb-0"><i class="bi bi-bell"></i> Alerts</h4>
      <div class="btn-group btn-group-sm" role="group" aria-label="Filter">
        <button type="button" class="btn" [class.btn-primary]="activeOnly()" [class.btn-outline-secondary]="!activeOnly()" (click)="setActive(true)">
          Active @if (activeCount()) { <span class="badge text-bg-light ms-1">{{ activeCount() }}</span> }
        </button>
        <button type="button" class="btn" [class.btn-primary]="!activeOnly()" [class.btn-outline-secondary]="activeOnly()" (click)="setActive(false)">
          History
        </button>
      </div>
    </div>

    @if (loading()) {
      <div class="text-secondary"><span class="spinner-border spinner-border-sm"></span> Loading…</div>
    } @else if (alerts().length === 0) {
      <div class="alert alert-success mb-0"><i class="bi bi-check-circle"></i>
        {{ activeOnly() ? 'No active alerts — all clear.' : 'No alerts recorded.' }}
      </div>
    } @else {
      <div class="list-group">
        @for (a of alerts(); track a.id) {
          <div class="list-group-item d-flex align-items-start gap-3"
               [class.list-group-item-warning]="a.cleared_at === null && a.severity === 'warning'"
               [class.list-group-item-danger]="a.cleared_at === null && a.severity === 'critical'">
            <span class="badge align-self-center text-bg-{{ severityClass(a) }}">{{ a.severity }}</span>
            <div class="flex-grow-1">
              <div class="fw-semibold">{{ a.message }}</div>
              <div class="small text-secondary">
                {{ a.metric }}{{ a.value !== null ? ' = ' + a.value : '' }}
                @if (a.device_id) { · {{ a.device_id }} }
                · {{ a.fired_at * 1000 | date: 'MMM d, HH:mm' }}
                @if (a.cleared_at !== null) {
                  · <span class="text-success">cleared {{ a.cleared_at * 1000 | date: 'HH:mm' }}</span>
                } @else {
                  · <span class="text-danger">active</span>
                }
                @if (a.acked_at !== null) { · <span class="text-secondary">acknowledged</span> }
              </div>
            </div>
            <div class="text-nowrap align-self-center">
              @if (a.acked_at === null) {
                <button class="btn btn-sm btn-outline-secondary me-1" (click)="ack(a)">Ack</button>
              }
              <button class="btn btn-sm btn-outline-secondary" (click)="snooze(a)">Snooze 1h</button>
            </div>
          </div>
        }
      </div>
    }
  `,
})
export class AlertsPage implements OnInit {
  private readonly api = inject(ApiService);

  readonly activeOnly = signal(true);
  readonly alerts = signal<Alert[]>([]);
  readonly activeCount = signal(0);
  readonly loading = signal(true);

  ngOnInit(): void {
    this.refresh();
  }

  setActive(active: boolean): void {
    this.activeOnly.set(active);
    this.refresh();
  }

  private refresh(): void {
    this.loading.set(true);
    this.api.getAlerts(this.activeOnly(), 200).subscribe({
      next: (r) => {
        this.alerts.set(r.alerts);
        this.activeCount.set(r.active_count);
        this.loading.set(false);
      },
      error: () => {
        this.alerts.set([]);
        this.loading.set(false);
      },
    });
  }

  ack(a: Alert): void {
    this.api.ackAlert(a.id).subscribe({ next: () => this.refresh() });
  }

  snooze(a: Alert): void {
    this.api.snoozeAlert(a.id, 60).subscribe({ next: () => this.refresh() });
  }

  severityClass = (a: Alert): string =>
    a.severity === 'critical' ? 'danger' : a.severity === 'warning' ? 'warning' : 'secondary';
}
