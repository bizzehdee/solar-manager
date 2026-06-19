import { Component, OnInit, inject, signal } from '@angular/core';
import { DatePipe } from '@angular/common';
import { FormsModule } from '@angular/forms';

import { ApiService } from '../../core/api.service';
import { Alert, AlertRule, AlertRuleOptions, DeviceConfig } from '../../core/models';

// Alerts (plan.md §15). Two tabs:
//   • Inbox (T082): active + history with ack/snooze — alerts are produced server-side.
//   • Rules (L11): create/edit/delete the rules the engine evaluates. The API + engine
//     already back this; defaults ship on. Editing here reloads the engine on the next tick.
@Component({
  selector: 'app-alerts',
  imports: [DatePipe, FormsModule],
  template: `
    <div class="d-flex align-items-center justify-content-between mb-3 flex-wrap gap-2">
      <h4 class="mb-0"><i class="bi bi-bell"></i> Alerts</h4>
      <ul class="nav nav-pills">
        <li class="nav-item">
          <button class="nav-link" [class.active]="tab() === 'inbox'" (click)="tab.set('inbox')">Inbox</button>
        </li>
        <li class="nav-item">
          <button class="nav-link" [class.active]="tab() === 'rules'" (click)="showRules()">Rules</button>
        </li>
      </ul>
    </div>

    @if (tab() === 'inbox') {
      <div class="d-flex justify-content-end mb-3">
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
    } @else {
      <!-- Rules editor (L11) -->
      <div class="d-flex justify-content-end mb-2">
        <button class="btn btn-sm btn-primary" (click)="newRule()" [disabled]="!!editing()">
          <i class="bi bi-plus-lg"></i> New rule
        </button>
      </div>

      @if (rulesLoading()) {
        <div class="text-secondary"><span class="spinner-border spinner-border-sm"></span> Loading…</div>
      } @else {
        <div class="list-group mb-3">
          @for (r of rules(); track r.id) {
            <div class="list-group-item d-flex align-items-center gap-3" [class.opacity-50]="!r.enabled">
              <div class="form-check form-switch m-0">
                <input class="form-check-input" type="checkbox" role="switch"
                       [attr.aria-label]="'Enable ' + r.name"
                       [checked]="r.enabled" (change)="toggle(r)" />
              </div>
              <span class="badge align-self-center text-bg-{{ sevClass(r.severity) }}">{{ r.severity }}</span>
              <div class="flex-grow-1">
                <div class="fw-semibold">{{ r.name }}</div>
                <div class="small text-secondary">
                  {{ metricLabel(r.metric) }} {{ opLabel(r.op) }} {{ r.threshold }}
                  @if (r.device_id) { · {{ r.device_id }} }
                  @if (r.channels.length) { · {{ r.channels.join(', ') }} }
                </div>
              </div>
              <div class="text-nowrap">
                <button class="btn btn-sm btn-outline-secondary me-1" (click)="edit(r)" [disabled]="!!editing()">Edit</button>
                <button class="btn btn-sm btn-outline-danger" (click)="remove(r)">Delete</button>
              </div>
            </div>
          } @empty {
            <div class="alert alert-secondary mb-0">No rules — add one.</div>
          }
        </div>
      }

      @if (editing(); as e) {
        <div class="card">
          <div class="card-header">{{ creating() ? 'New rule' : 'Edit rule' }}</div>
          <div class="card-body">
            @if (formError()) { <div class="alert alert-danger py-2">{{ formError() }}</div> }
            <form (ngSubmit)="save()">
              <div class="row g-3">
                <div class="col-12 col-md-6">
                  <label class="form-label small text-secondary" for="r-name">Name</label>
                  <input id="r-name" class="form-control" [(ngModel)]="e.name" name="name" required />
                </div>
                <div class="col-6 col-md-3">
                  <label class="form-label small text-secondary" for="r-sev">Severity</label>
                  <select id="r-sev" class="form-select" [(ngModel)]="e.severity" name="severity">
                    @for (s of options().severities; track s) { <option [value]="s">{{ s }}</option> }
                  </select>
                </div>
                <div class="col-6 col-md-3">
                  <label class="form-label small text-secondary" for="r-dev">Device</label>
                  <select id="r-dev" class="form-select" [(ngModel)]="e.device_id" name="device">
                    <option [ngValue]="null">Default (first)</option>
                    @for (d of devices(); track d.id) { <option [ngValue]="d.id">{{ d.name || d.id }}</option> }
                  </select>
                </div>

                <div class="col-12 col-md-6">
                  <label class="form-label small text-secondary" for="r-metric">Metric</label>
                  <select id="r-metric" class="form-select" [(ngModel)]="e.metric" name="metric">
                    @for (m of options().metrics; track m) { <option [value]="m">{{ metricLabel(m) }}</option> }
                  </select>
                </div>
                <div class="col-6 col-md-2">
                  <label class="form-label small text-secondary" for="r-op">Condition</label>
                  <select id="r-op" class="form-select" [(ngModel)]="e.op" name="op">
                    @for (o of options().ops; track o) { <option [value]="o">{{ opLabel(o) }}</option> }
                  </select>
                </div>
                <div class="col-6 col-md-4">
                  <label class="form-label small text-secondary" for="r-thr">Threshold</label>
                  <input id="r-thr" type="number" step="any" class="form-control" [(ngModel)]="e.threshold" name="threshold" />
                </div>

                <div class="col-6 col-md-3">
                  <label class="form-label small text-secondary" for="r-hys">Hysteresis</label>
                  <input id="r-hys" type="number" step="any" class="form-control" [(ngModel)]="e.hysteresis" name="hysteresis" />
                </div>
                <div class="col-6 col-md-3">
                  <label class="form-label small text-secondary" for="r-deb">Debounce (s)</label>
                  <input id="r-deb" type="number" step="any" class="form-control" [(ngModel)]="e.debounce_s" name="debounce" />
                </div>
                <div class="col-6 col-md-3">
                  <label class="form-label small text-secondary" for="r-qs">Quiet from (h)</label>
                  <input id="r-qs" type="number" min="0" max="23" class="form-control" [(ngModel)]="quietStart" name="quietStart" placeholder="—" />
                </div>
                <div class="col-6 col-md-3">
                  <label class="form-label small text-secondary" for="r-qe">Quiet to (h)</label>
                  <input id="r-qe" type="number" min="0" max="23" class="form-control" [(ngModel)]="quietEnd" name="quietEnd" placeholder="—" />
                </div>

                <div class="col-12">
                  <label class="form-label small text-secondary" for="r-msg">Message (optional)</label>
                  <input id="r-msg" class="form-control" [(ngModel)]="e.message" name="message" />
                </div>

                <div class="col-12">
                  <label class="form-label small text-secondary d-block">Notify (in-app inbox is always recorded)</label>
                  @for (c of options().channels; track c) {
                    <div class="form-check form-check-inline">
                      <input class="form-check-input" type="checkbox" [id]="'ch-' + c"
                             [checked]="e.channels.includes(c)" (change)="toggleChannel(c)" />
                      <label class="form-check-label" [for]="'ch-' + c">{{ c }}</label>
                    </div>
                  }
                </div>
              </div>

              <div class="mt-3 d-flex gap-2">
                <button type="submit" class="btn btn-primary"><i class="bi bi-save"></i> Save rule</button>
                <button type="button" class="btn btn-outline-secondary" (click)="cancel()">Cancel</button>
              </div>
            </form>
          </div>
        </div>
      }
    }
  `,
})
export class AlertsPage implements OnInit {
  private readonly api = inject(ApiService);

  readonly tab = signal<'inbox' | 'rules'>('inbox');

  // Inbox
  readonly activeOnly = signal(true);
  readonly alerts = signal<Alert[]>([]);
  readonly activeCount = signal(0);
  readonly loading = signal(true);

  // Rules
  readonly rules = signal<AlertRule[]>([]);
  readonly rulesLoading = signal(false);
  readonly options = signal<AlertRuleOptions>({ metrics: [], ops: [], severities: [], channels: [] });
  readonly devices = signal<DeviceConfig[]>([]);
  readonly editing = signal<AlertRule | null>(null);
  readonly creating = signal(false);
  readonly formError = signal<string | null>(null);
  quietStart: number | null = null;
  quietEnd: number | null = null;

  ngOnInit(): void {
    this.refresh();
  }

  // --- inbox ------------------------------------------------------------------
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

  severityClass = (a: Alert): string => this.sevClass(a.severity);
  sevClass = (s: string): string => (s === 'critical' ? 'danger' : s === 'warning' ? 'warning' : 'secondary');

  // --- rules ------------------------------------------------------------------
  showRules(): void {
    this.tab.set('rules');
    if (this.options().metrics.length === 0) {
      this.api.getAlertRuleOptions().subscribe({ next: (o) => this.options.set(o) });
      this.api.getDevices().subscribe({ next: (r) => this.devices.set(r.devices) });
    }
    this.loadRules();
  }

  private loadRules(): void {
    this.rulesLoading.set(true);
    this.api.getAlertRules().subscribe({
      next: (r) => {
        this.rules.set(r.rules);
        this.rulesLoading.set(false);
      },
      error: () => {
        this.rules.set([]);
        this.rulesLoading.set(false);
      },
    });
  }

  newRule(): void {
    this.creating.set(true);
    this.formError.set(null);
    this.quietStart = null;
    this.quietEnd = null;
    this.editing.set({
      id: '', name: '', metric: this.options().metrics[0] || 'battery_soc_pct', op: 'lt',
      threshold: 0, hysteresis: 0, debounce_s: 0, severity: 'warning', channels: [],
      quiet_hours: null, device_id: null, message: '', enabled: true,
    });
  }

  edit(r: AlertRule): void {
    this.creating.set(false);
    this.formError.set(null);
    this.quietStart = r.quiet_hours ? r.quiet_hours[0] : null;
    this.quietEnd = r.quiet_hours ? r.quiet_hours[1] : null;
    this.editing.set({ ...r, channels: [...r.channels] });
  }

  cancel(): void {
    this.editing.set(null);
    this.formError.set(null);
  }

  toggleChannel(c: string): void {
    const e = this.editing();
    if (!e) return;
    e.channels = e.channels.includes(c) ? e.channels.filter((x) => x !== c) : [...e.channels, c];
  }

  toggle(r: AlertRule): void {
    this.api.putAlertRule(r.id, { ...r, enabled: !r.enabled }).subscribe({ next: () => this.loadRules() });
  }

  save(): void {
    const e = this.editing();
    if (!e) return;
    const name = (e.name || '').trim();
    if (!name) {
      this.formError.set('Name is required.');
      return;
    }
    const id = this.creating() ? this.slug(name) || `rule-${Date.now()}` : e.id;
    const quiet =
      this.quietStart !== null && this.quietEnd !== null
        ? ([Number(this.quietStart), Number(this.quietEnd)] as [number, number])
        : null;
    const body: AlertRule = { ...e, id, name, quiet_hours: quiet };
    this.api.putAlertRule(id, body).subscribe({
      next: () => {
        this.editing.set(null);
        this.loadRules();
      },
      error: (err) => this.formError.set(err?.error?.detail || 'Could not save the rule.'),
    });
  }

  remove(r: AlertRule): void {
    this.api.deleteAlertRule(r.id).subscribe({
      next: () => {
        if (this.editing()?.id === r.id) this.editing.set(null);
        this.loadRules();
      },
    });
  }

  private slug = (s: string): string =>
    s.toLowerCase().trim().replace(/[^a-z0-9]+/g, '_').replace(/^_+|_+$/g, '');

  metricLabel = (m: string): string =>
    m === '__stale_s__' ? 'Data age (stale seconds)' : m === '__fault_count__' ? 'Active fault count' : m;

  opLabel = (o: string): string =>
    ({ lt: '<', le: '≤', gt: '>', ge: '≥', eq: '=', ne: '≠' }[o] ?? o);
}
