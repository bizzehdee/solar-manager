import { Component, OnInit, computed, inject, signal } from '@angular/core';
import { DatePipe } from '@angular/common';
import { FormsModule } from '@angular/forms';

import { ApiService } from '../../core/api.service';
import {
  AutomationAction,
  AutomationChange,
  AutomationCondition,
  AutomationOptions,
  AutomationPreview,
  AutomationRule,
  AutomationTargetOption,
} from '../../core/models';

// Automation (plan.md §18 / L03e-4): build/edit/prioritise rules and see a **live preview** of
// what they would set right now. Gated by SOLARVOLT_ENABLE_AUTOMATION — when off, the API 403s
// and this page shows how to turn it on. Rules suggest only here; opt-in apply is a later slice.
@Component({
  selector: 'app-automation',
  imports: [FormsModule, DatePipe],
  template: `
    <div class="d-flex align-items-center justify-content-between mb-3 flex-wrap gap-2">
      <h4 class="mb-0"><i class="bi bi-robot"></i> Automation</h4>
      @if (enabled()) {
        <button class="btn btn-sm btn-primary" (click)="newRule()" [disabled]="!!editing()">
          <i class="bi bi-plus-lg"></i> New rule
        </button>
      }
    </div>

    @if (disabled()) {
      <div class="alert alert-secondary">
        <i class="bi bi-lock"></i> Automation is disabled. Set <code>SOLARVOLT_ENABLE_AUTOMATION=true</code>
        and restart to build rules. Rules only ever <em>suggest</em> until apply is enabled separately.
      </div>
    } @else if (loading()) {
      <div class="text-secondary"><span class="spinner-border spinner-border-sm"></span> Loading…</div>
    } @else {
      <div class="row g-3">
        <!-- Rules + editor -->
        <div class="col-12 col-lg-7">
          <div class="list-group mb-3">
            @for (r of rules(); track r.id) {
              <div class="list-group-item d-flex align-items-center gap-3" [class.opacity-50]="!r.enabled">
                <div class="form-check form-switch m-0">
                  <input class="form-check-input" type="checkbox" role="switch"
                         [attr.aria-label]="'Arm ' + r.name" [checked]="r.enabled" (change)="toggleRule(r)" />
                </div>
                <div class="flex-grow-1">
                  <div class="fw-semibold">{{ r.name }} <span class="badge text-bg-light">P{{ r.priority }}</span></div>
                  <div class="small text-secondary">
                    {{ r.conditions.length }} condition(s) · {{ r.actions.length }} action(s) · match {{ r.match }}
                  </div>
                </div>
                <div class="text-nowrap">
                  <button class="btn btn-sm btn-outline-secondary me-1" (click)="editRule(r)" [disabled]="!!editing()">Edit</button>
                  <button class="btn btn-sm btn-outline-danger" (click)="removeRule(r)">Delete</button>
                </div>
              </div>
            } @empty {
              <div class="alert alert-secondary mb-0">No rules yet — add one.</div>
            }
          </div>

          @if (editing(); as e) {
            <div class="card">
              <div class="card-header">{{ creating() ? 'New rule' : 'Edit rule' }}</div>
              <div class="card-body">
                @if (formError()) { <div class="alert alert-danger py-2">{{ formError() }}</div> }
                <form (ngSubmit)="saveRule()">
                <div class="row g-2 mb-3">
                  <div class="col-12 col-md-6">
                    <label class="form-label small text-secondary" for="a-name">Name</label>
                    <input id="a-name" class="form-control" [(ngModel)]="e.name" name="name" />
                  </div>
                  <div class="col-6 col-md-3">
                    <label class="form-label small text-secondary" for="a-match">Match</label>
                    <select id="a-match" class="form-select" [(ngModel)]="e.match" name="match">
                      @for (m of options().match_modes; track m) { <option [value]="m">{{ m }}</option> }
                    </select>
                  </div>
                  <div class="col-6 col-md-3">
                    <label class="form-label small text-secondary" for="a-prio">Priority</label>
                    <input id="a-prio" type="number" class="form-control" [(ngModel)]="e.priority" name="priority" />
                  </div>
                </div>

                <!-- Conditions -->
                <h6 class="text-secondary">Conditions</h6>
                @for (c of e.conditions; track $index; let ci = $index) {
                  <div class="border rounded p-2 mb-2">
                    <div class="d-flex gap-2 align-items-center mb-2">
                      <select class="form-select form-select-sm" style="max-width: 12rem"
                              [ngModel]="c.kind" (ngModelChange)="setKind(c, $event)" [name]="'ckind' + $index">
                        @for (k of options().condition_kinds; track k) { <option [value]="k">{{ condLabel(k) }}</option> }
                      </select>
                      <button type="button" class="btn btn-sm btn-outline-danger ms-auto" (click)="removeCondition($index)">
                        <i class="bi bi-x"></i>
                      </button>
                    </div>
                    @switch (c.kind) {
                      @case ('day_of_week') {
                        <div class="d-flex flex-wrap gap-2">
                          @for (d of weekdays; track d.i) {
                            <div class="form-check form-check-inline">
                              <input class="form-check-input" type="checkbox" [id]="'d' + ci + '-' + d.i"
                                     [checked]="hasDay(c, d.i)" (change)="toggleDay(c, d.i)" />
                              <label class="form-check-label small" [for]="'d' + ci + '-' + d.i">{{ d.label }}</label>
                            </div>
                          }
                        </div>
                      }
                      @case ('time_window') {
                        <div class="row g-2">
                          <div class="col-6"><label class="small text-secondary">From hour</label>
                            <input type="number" min="0" max="23" class="form-control form-control-sm" [(ngModel)]="c.params['start_hour']" [name]="'cts' + $index" /></div>
                          <div class="col-6"><label class="small text-secondary">To hour</label>
                            <input type="number" min="0" max="23" class="form-control form-control-sm" [(ngModel)]="c.params['end_hour']" [name]="'cte' + $index" /></div>
                        </div>
                      }
                      @case ('date_range') {
                        <div class="row g-2">
                          <div class="col-6"><label class="small text-secondary">From (MM-DD)</label>
                            <input class="form-control form-control-sm" [(ngModel)]="c.params['start']" [name]="'cds' + $index" placeholder="11-01" /></div>
                          <div class="col-6"><label class="small text-secondary">To (MM-DD)</label>
                            <input class="form-control form-control-sm" [(ngModel)]="c.params['end']" [name]="'cde' + $index" placeholder="02-28" /></div>
                        </div>
                      }
                      @case ('metric') {
                        <div class="row g-2">
                          <div class="col-6"><label class="small text-secondary">Metric</label>
                            <select class="form-select form-select-sm" [(ngModel)]="c.params['metric']" [name]="'cm' + $index">
                              @for (m of options().metrics; track m) { <option [value]="m">{{ m }}</option> }
                            </select></div>
                          <div class="col-3"><label class="small text-secondary">Op</label>
                            <select class="form-select form-select-sm" [(ngModel)]="c.params['op']" [name]="'cmo' + $index">
                              @for (o of options().ops; track o) { <option [value]="o">{{ o }}</option> }
                            </select></div>
                          <div class="col-3"><label class="small text-secondary">Value</label>
                            <input type="number" step="any" class="form-control form-control-sm" [(ngModel)]="c.params['threshold']" [name]="'cmt' + $index" /></div>
                        </div>
                      }
                      @case ('tariff_window') {
                        <label class="small text-secondary">Window</label>
                        <select class="form-select form-select-sm" [(ngModel)]="c.params['window']" [name]="'ctw' + $index">
                          <option value="cheapest">Cheapest</option>
                          <option value="peak">Peak</option>
                        </select>
                      }
                    }
                  </div>
                }
                <button type="button" class="btn btn-sm btn-outline-secondary mb-3" (click)="addCondition()">
                  <i class="bi bi-plus-lg"></i> Add condition
                </button>

                <!-- Actions -->
                <h6 class="text-secondary">Actions</h6>
                @for (a of e.actions; track $index) {
                  <div class="border rounded p-2 mb-2">
                    <div class="row g-2 align-items-end">
                      <div class="col-12 col-md-5">
                        <label class="small text-secondary">Setting</label>
                        <select class="form-select form-select-sm" [ngModel]="targetKey(a)" (ngModelChange)="setTarget(a, $event)" [name]="'at' + $index">
                          @for (t of options().targets; track t.section + t.field) {
                            <option [value]="t.section + '|' + t.field">{{ t.section_label }} · {{ t.label }}</option>
                          }
                        </select>
                      </div>
                      @if (isRepeating(a)) {
                        <div class="col-4 col-md-2">
                          <label class="small text-secondary">Slot</label>
                          <input type="number" min="0" class="form-control form-control-sm" [(ngModel)]="a.target.index" [name]="'ai' + $index" />
                        </div>
                      }
                      <div class="col-4 col-md-3">
                        <label class="small text-secondary">Value</label>
                        @if (targetType(a) === 'bool') {
                          <div class="form-check"><input class="form-check-input" type="checkbox" [(ngModel)]="a.value" [name]="'av' + $index" /></div>
                        } @else if (targetType(a) === 'number' || targetType(a) === 'int') {
                          <input type="number" step="any" class="form-control form-control-sm" [(ngModel)]="a.value" [name]="'av' + $index" />
                        } @else {
                          <input class="form-control form-control-sm" [(ngModel)]="a.value" [name]="'av' + $index" />
                        }
                      </div>
                      <div class="col-4 col-md-2">
                        <div class="form-check form-switch mt-3">
                          <input class="form-check-input" type="checkbox" role="switch" [(ngModel)]="a.enabled" [name]="'ae' + $index" />
                          <label class="form-check-label small">Armed</label>
                        </div>
                      </div>
                    </div>
                    <div class="d-flex align-items-center mt-1">
                      <span class="badge text-bg-{{ statusClass(targetStatus(a)) }}">{{ targetStatus(a) }}</span>
                      <button type="button" class="btn btn-sm btn-outline-danger ms-auto" (click)="removeAction($index)"><i class="bi bi-x"></i></button>
                    </div>
                  </div>
                }
                <button type="button" class="btn btn-sm btn-outline-secondary mb-3" (click)="addAction()">
                  <i class="bi bi-plus-lg"></i> Add action
                </button>

                <div class="d-flex gap-2">
                  <button type="submit" class="btn btn-primary"><i class="bi bi-save"></i> Save rule</button>
                  <button type="button" class="btn btn-outline-secondary" (click)="cancel()">Cancel</button>
                </div>
                </form>
              </div>
            </div>
          }
        </div>

        <!-- Live preview -->
        <div class="col-12 col-lg-5">
          <div class="card">
            <div class="card-header d-flex justify-content-between align-items-center">
              <span><i class="bi bi-eye"></i> What it would do now</span>
              <button class="btn btn-sm btn-outline-secondary" (click)="refreshPreview()"><i class="bi bi-arrow-clockwise"></i></button>
            </div>
            <div class="card-body">
              @if (preview(); as p) {
                <div class="small text-secondary mb-2">As of {{ p.now | date: 'EEE HH:mm' }} · {{ p.rule_count }} rule(s)</div>
                @if (p.decision.changes.length === 0) {
                  <div class="text-secondary">No rules match right now — nothing to set.</div>
                } @else {
                  @for (c of p.decision.changes; track $index) {
                    <div class="d-flex align-items-start gap-2 py-1 border-bottom">
                      <span class="badge text-bg-{{ statusClass(c.status) }}">{{ c.status }}</span>
                      <div class="flex-grow-1 small">
                        <div><code>{{ changeLabel(c) }}</code> = <strong>{{ c.value }}</strong></div>
                        <div class="text-secondary">
                          {{ c.rule_name }} ·
                          @if (c.will_apply) { <span class="text-success">would apply</span> }
                          @else { <span class="text-warning">preview only</span> }
                        </div>
                      </div>
                    </div>
                  }
                  @if (p.decision.overridden.length) {
                    <div class="small text-secondary mt-2">
                      {{ p.decision.overridden.length }} change(s) overridden by higher-priority rules.
                    </div>
                  }
                }
              } @else {
                <div class="text-secondary">No preview.</div>
              }
            </div>
          </div>
        </div>
      </div>
    }
  `,
})
export class AutomationPage implements OnInit {
  private readonly api = inject(ApiService);

  readonly enabled = signal<boolean | null>(null);
  readonly disabled = computed(() => this.enabled() === false);
  readonly loading = signal(true);
  readonly rules = signal<AutomationRule[]>([]);
  readonly options = signal<AutomationOptions>({ condition_kinds: [], ops: [], metrics: [], match_modes: ['all', 'any'], targets: [] });
  readonly preview = signal<AutomationPreview | null>(null);
  readonly editing = signal<AutomationRule | null>(null);
  readonly creating = signal(false);
  readonly formError = signal<string | null>(null);

  readonly weekdays = [
    { i: 0, label: 'Mon' }, { i: 1, label: 'Tue' }, { i: 2, label: 'Wed' }, { i: 3, label: 'Thu' },
    { i: 4, label: 'Fri' }, { i: 5, label: 'Sat' }, { i: 6, label: 'Sun' },
  ];

  ngOnInit(): void {
    this.api.getHealth().subscribe({
      next: (h) => {
        this.enabled.set(h.automation_enabled === true);
        if (h.automation_enabled) this.load();
        else this.loading.set(false);
      },
      error: () => { this.enabled.set(false); this.loading.set(false); },
    });
  }

  private load(): void {
    this.api.getAutomationOptions().subscribe({ next: (o) => this.options.set(o) });
    this.loadRules();
    this.refreshPreview();
  }

  private loadRules(): void {
    this.loading.set(true);
    this.api.getAutomationRules().subscribe({
      next: (r) => { this.rules.set(r.rules); this.loading.set(false); },
      error: () => { this.rules.set([]); this.loading.set(false); },
    });
  }

  refreshPreview(): void {
    this.api.getAutomationPreview().subscribe({ next: (p) => this.preview.set(p), error: () => this.preview.set(null) });
  }

  // --- rule list actions ------------------------------------------------------
  toggleRule(r: AutomationRule): void {
    this.api.putAutomationRule(r.id, { ...r, enabled: !r.enabled }).subscribe({ next: () => this.afterSave() });
  }

  removeRule(r: AutomationRule): void {
    this.api.deleteAutomationRule(r.id).subscribe({
      next: () => { if (this.editing()?.id === r.id) this.editing.set(null); this.afterSave(); },
    });
  }

  // --- editor -----------------------------------------------------------------
  newRule(): void {
    this.creating.set(true);
    this.formError.set(null);
    this.editing.set({ id: '', name: '', match: 'all', priority: 0, enabled: false, conditions: [], actions: [] });
  }

  editRule(r: AutomationRule): void {
    this.creating.set(false);
    this.formError.set(null);
    this.editing.set(structuredClone(r));
  }

  cancel(): void { this.editing.set(null); this.formError.set(null); }

  addCondition(): void {
    const e = this.editing();
    if (e) e.conditions = [...e.conditions, this.defaultCondition(this.options().condition_kinds[0] || 'day_of_week')];
  }

  removeCondition(i: number): void {
    const e = this.editing();
    if (e) e.conditions = e.conditions.filter((_, idx) => idx !== i);
  }

  setKind(c: AutomationCondition, kind: string): void {
    const fresh = this.defaultCondition(kind);
    c.kind = fresh.kind;
    c.params = fresh.params;
  }

  private defaultCondition(kind: string): AutomationCondition {
    switch (kind) {
      case 'time_window': return { kind, params: { start_hour: 0, end_hour: 6 } };
      case 'date_range': return { kind, params: { start: '11-01', end: '02-28' } };
      case 'metric': return { kind, params: { metric: this.options().metrics[0] || 'battery_soc_pct', op: 'lt', threshold: 20 } };
      case 'tariff_window': return { kind, params: { window: 'cheapest' } };
      default: return { kind: 'day_of_week', params: { days: [] } };
    }
  }

  hasDay = (c: AutomationCondition, d: number): boolean => (c.params['days'] || []).includes(d);

  toggleDay(c: AutomationCondition, d: number): void {
    const days: number[] = c.params['days'] || [];
    c.params['days'] = days.includes(d) ? days.filter((x) => x !== d) : [...days, d].sort((a, b) => a - b);
  }

  addAction(): void {
    const e = this.editing();
    const t = this.options().targets[0];
    if (e && t) {
      e.actions = [...e.actions, {
        target: { section: t.section, field: t.field, index: t.repeating ? 0 : null },
        value: t.type === 'bool' ? false : 0, enabled: false,
      }];
    }
  }

  removeAction(i: number): void {
    const e = this.editing();
    if (e) e.actions = e.actions.filter((_, idx) => idx !== i);
  }

  targetKey = (a: AutomationAction): string => `${a.target.section}|${a.target.field}`;

  setTarget(a: AutomationAction, key: string): void {
    const [section, field] = key.split('|');
    const opt = this.options().targets.find((t) => t.section === section && t.field === field);
    a.target.section = section;
    a.target.field = field;
    a.target.index = opt?.repeating ? (a.target.index ?? 0) : null;
  }

  private optFor(a: AutomationAction): AutomationTargetOption | undefined {
    return this.options().targets.find((t) => t.section === a.target.section && t.field === a.target.field);
  }
  targetType = (a: AutomationAction): string => this.optFor(a)?.type || 'number';
  isRepeating = (a: AutomationAction): boolean => this.optFor(a)?.repeating === true;
  targetStatus = (a: AutomationAction): string => this.optFor(a)?.status || 'ok';

  saveRule(): void {
    const e = this.editing();
    if (!e) return;
    const name = (e.name || '').trim();
    if (!name) { this.formError.set('Name is required.'); return; }
    const id = this.creating() ? this.slug(name) || `rule-${Date.now()}` : e.id;
    this.api.putAutomationRule(id, { ...e, id, name }).subscribe({
      next: () => { this.editing.set(null); this.afterSave(); },
      error: (err) => this.formError.set(err?.error?.detail || 'Could not save the rule.'),
    });
  }

  private afterSave(): void {
    this.loadRules();
    this.refreshPreview();
  }

  private slug = (s: string): string =>
    s.toLowerCase().trim().replace(/[^a-z0-9]+/g, '_').replace(/^_+|_+$/g, '');

  condLabel = (k: string): string =>
    ({ day_of_week: 'Day of week', time_window: 'Time of day', date_range: 'Date range',
       metric: 'Metric threshold', tariff_window: 'Tariff window' }[k] ?? k);

  statusClass = (s: string): string =>
    s === 'blocked' ? 'danger' : s === 'at_risk' ? 'warning' : 'success';

  changeLabel = (c: AutomationChange): string =>
    c.target.index !== null ? `${c.target.section}[${c.target.index}].${c.target.field}` : `${c.target.section}.${c.target.field}`;
}
