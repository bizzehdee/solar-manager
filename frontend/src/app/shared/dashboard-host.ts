import { NgComponentOutlet } from '@angular/common';
import {
  AfterViewInit,
  Component,
  ElementRef,
  OnDestroy,
  effect,
  inject,
  input,
  output,
  signal,
  viewChild,
} from '@angular/core';
import { FormsModule } from '@angular/forms';
import { GridStack, GridStackNode } from 'gridstack';

import { DashboardConfig, DashboardData, DashboardWidget } from '../core/models';
import { downloadDashboard, parseDashboard } from '../core/dashboard-file';
import { metricUnit } from '../core/metric-units';
import { WIDGET_REGISTRY, widgetDef, unknownWidgetTypes } from './widget-registry';

// Layout host + editor for L06 dashboards (T_DB2 + T_DB7). Loads a DashboardConfig, lays its
// widgets out on a 12-column GridStack, and — in edit mode — supports drag/resize, add/remove and
// per-widget configuration, emitting the new layout on Save. GridStack owns the DOM once laid out,
// so the item list is snapshotted from the input and only re-rendered on structural changes
// (add/remove/dashboard switch), after which GridStack is re-initialised.

const COLUMNS = 12;

/** Apply GridStack's saved node positions onto the widgets, matched by the `gs-id` we stamped as
 *  the widget's index. Every widget is preserved (count + order kept) — only positions of reported
 *  nodes are updated — so a partial/empty save (e.g. mid re-init) never drops widgets. Pure +
 *  exported so it's unit-testable without a DOM. */
export function mergeLayout(widgets: DashboardWidget[], nodes: GridStackNode[]): DashboardWidget[] {
  const byId = new Map(nodes.map((n) => [Number(n.id), n]));
  return widgets.map((w, i) => {
    const n = byId.get(i);
    return n ? { ...w, x: n.x ?? w.x, y: n.y ?? w.y, w: n.w ?? w.w, h: n.h ?? w.h } : w;
  });
}

@Component({
  selector: 'app-dashboard-host',
  imports: [NgComponentOutlet, FormsModule],
  template: `
    <!-- One toolbar row: the page's title (projected) on the left, all actions on the right —
         so Edit / Reset / Export / Import sit together beside the title instead of stacking. -->
    <div class="d-flex flex-wrap gap-2 mb-3 align-items-center">
      <ng-content select="[dashTitle]" />
      @if (!editing()) {
        <div class="ms-auto d-flex flex-wrap gap-2">
          <button class="btn btn-sm btn-outline-secondary" (click)="enterEdit()">
            <i class="bi bi-pencil"></i> Edit
          </button>
          @if (canReset()) {
            <button class="btn btn-sm btn-outline-secondary" (click)="reset.emit()" title="Reset to the default layout">
              <i class="bi bi-arrow-counterclockwise"></i> Reset to default
            </button>
          }
          <button class="btn btn-sm btn-outline-secondary" (click)="exportLayout()" title="Download this layout as JSON">
            <i class="bi bi-download"></i> Export
          </button>
          <button class="btn btn-sm btn-outline-secondary" (click)="importInput.click()" title="Replace this layout from a JSON file">
            <i class="bi bi-upload"></i> Import
          </button>
          <input #importInput type="file" accept=".json,application/json" class="d-none" (change)="onImportFile($event)" />
        </div>
      } @else {
        <select class="form-select form-select-sm w-auto" #addSel (change)="addWidget(addSel.value); addSel.value=''">
          <option value="" selected>+ Add widget…</option>
          @for (t of widgetTypes; track t.type) {
            <option [value]="t.type">{{ t.label }}</option>
          }
        </select>
        <button class="btn btn-sm btn-primary ms-auto" (click)="save()"><i class="bi bi-save"></i> Save</button>
        <button class="btn btn-sm btn-outline-secondary" (click)="discard()">Discard</button>
      }
    </div>

    @if (notice(); as n) {
      <div class="alert alert-{{ n.cls }} py-2 d-flex justify-content-between align-items-center">
        <span>{{ n.text }}</span>
        <button class="btn-close" (click)="notice.set(null)" aria-label="Dismiss"></button>
      </div>
    }

    <div class="grid-stack" #grid>
      @for (w of items; track $index) {
        <div class="grid-stack-item" [attr.gs-id]="$index"
             [attr.gs-x]="w.x" [attr.gs-y]="w.y" [attr.gs-w]="w.w" [attr.gs-h]="w.h">
          <!-- The .grid-stack-item-content must keep GridStack's own positioning (its margin
               insets size it); the position-relative anchor for the edit overlay lives one level in. -->
          <div class="grid-stack-item-content">
            <div class="dash-widget">
              @if (editing()) {
                <div class="dash-overlay d-flex gap-1">
                  @if (defFor(w.type)?.configSchema?.length) {
                    <button class="btn btn-sm btn-light border" (click)="configure($index)" aria-label="Configure widget">
                      <i class="bi bi-gear"></i>
                    </button>
                  }
                  <button class="btn btn-sm btn-light border text-danger" (click)="removeAt($index)" aria-label="Remove widget">
                    <i class="bi bi-x-lg"></i>
                  </button>
                </div>
              }
              @if (defFor(w.type); as def) {
                <ng-container *ngComponentOutlet="def.component; inputs: def.inputs(w.config, data())" />
              } @else {
                <div class="card h-100"><div class="card-body d-flex align-items-center justify-content-center text-secondary small">
                  Unknown widget: {{ w.type }}
                </div></div>
              }
            </div>
          </div>
        </div>
      }
    </div>

    <!-- Config dialog for the selected widget (T_DB7). A Bootstrap modal (CSS-only, matching
         DialogHost) so it's centred over the page instead of stranded at the bottom. -->
    @if (editing() && configIndex() !== null && items[configIndex()!]; as w) {
      <div class="modal d-block" tabindex="-1" role="dialog" (keydown.escape)="configIndex.set(null)">
        <div class="modal-dialog modal-dialog-centered modal-lg">
          <div class="modal-content">
            <div class="modal-header">
              <h5 class="modal-title"><i class="bi bi-gear"></i> Configure {{ defFor(w.type)?.label || w.type }}</h5>
              <button type="button" class="btn-close" aria-label="Close" (click)="configIndex.set(null)"></button>
            </div>
            <div class="modal-body">
              <div class="row g-3">
                @for (f of defFor(w.type)?.configSchema || []; track f.key) {
                  <div class="col-12 col-md-6">
                    <label class="form-label small text-secondary" [attr.for]="'cfg-' + f.key">{{ f.label }}</label>
                    @if (f.type === 'metric') {
                      <select [id]="'cfg-' + f.key" class="form-select form-select-sm"
                              [ngModel]="configValue(w, f.key)" (ngModelChange)="setConfig(f.key, $event)">
                        @for (m of metricOptions(w, f.key); track m) { <option [value]="m">{{ m }}</option> }
                      </select>
                    } @else if (f.type === 'number') {
                      <input [id]="'cfg-' + f.key" type="number" class="form-control form-control-sm"
                             [ngModel]="configValue(w, f.key)" (ngModelChange)="setConfig(f.key, $event)" />
                    } @else if (f.type === 'select') {
                      <select [id]="'cfg-' + f.key" class="form-select form-select-sm"
                              [ngModel]="configValue(w, f.key)" (ngModelChange)="setConfig(f.key, $event)">
                        @for (o of f.options || []; track o.value) { <option [value]="o.value">{{ o.label }}</option> }
                      </select>
                    } @else if (f.type === 'icon') {
                      <div class="input-group input-group-sm">
                        <span class="input-group-text"><i class="bi {{ iconClass(configValue(w, f.key)) }}"></i></span>
                        <select [id]="'cfg-' + f.key" class="form-select form-select-sm"
                                [ngModel]="configValue(w, f.key)" (ngModelChange)="setConfig(f.key, $event)">
                          @for (ic of iconOptions; track ic.value) {
                            <option [value]="ic.value">{{ ic.label }}</option>
                          }
                        </select>
                      </div>
                    } @else if (f.type === 'role') {
                      <div class="input-group input-group-sm">
                        <span class="input-group-text p-1">
                          <span class="d-inline-block rounded border" style="width:1.1rem;height:1.1rem"
                                [style.background-color]="roleColor(configValue(w, f.key))"></span>
                        </span>
                        <select [id]="'cfg-' + f.key" class="form-select form-select-sm"
                                [ngModel]="configValue(w, f.key)" (ngModelChange)="setConfig(f.key, $event)">
                          @for (c of roleOptions; track c.value) {
                            <option [value]="c.value" [style.color]="c.color">{{ c.label }}</option>
                          }
                        </select>
                      </div>
                    } @else {
                      <input [id]="'cfg-' + f.key" class="form-control form-control-sm"
                             [placeholder]="f.key === 'unit' ? unitHint(w) : ''"
                             [ngModel]="configValue(w, f.key)" (ngModelChange)="setConfig(f.key, $event)" />
                    }
                  </div>
                }
              </div>
            </div>
            <div class="modal-footer">
              <button type="button" class="btn btn-primary" (click)="configIndex.set(null)">Done</button>
            </div>
          </div>
        </div>
      </div>
      <div class="modal-backdrop show"></div>
    }
  `,
})
export class DashboardHost implements AfterViewInit, OnDestroy {
  readonly dashboard = input.required<DashboardConfig>();
  readonly cellHeight = input('5rem');
  readonly data = input<DashboardData>({ metrics: {} });
  /** Show a "Reset to default" button (built-in dashboards only). */
  readonly canReset = input(false);

  /** Emitted on Save (or a successful Import) with the new layout — the page persists it. */
  readonly layoutSaved = output<DashboardWidget[]>();
  /** Emitted when the user clicks "Reset to default" — the page drops its override. */
  readonly reset = output<void>();

  /** Transient import feedback (success / unknown-widget warning / parse error). */
  readonly notice = signal<{ cls: string; text: string } | null>(null);

  private readonly gridEl = viewChild.required<ElementRef<HTMLElement>>('grid');
  private grid: GridStack | null = null;

  protected readonly defFor = widgetDef;
  protected readonly widgetTypes = Object.entries(WIDGET_REGISTRY).map(([type, def]) => ({ type, label: def.label }));
  // Widget "Colour" (role) field options: labelled by the closest actual colour, each carrying the
  // Bootstrap theme variable so the editor can paint a swatch / colour the option text.
  protected readonly roleOptions = [
    { value: 'primary', label: 'Blue', color: 'var(--bs-primary)' },
    { value: 'info', label: 'Cyan', color: 'var(--bs-info)' },
    { value: 'success', label: 'Green', color: 'var(--bs-success)' },
    { value: 'warning', label: 'Amber', color: 'var(--bs-warning)' },
    { value: 'danger', label: 'Red', color: 'var(--bs-danger)' },
    { value: 'secondary', label: 'Grey', color: 'var(--bs-secondary)' },
    { value: 'dark', label: 'Black', color: 'var(--bs-dark)' },
    { value: 'light', label: 'White', color: 'var(--bs-light)' },
    { value: 'body', label: 'Default', color: 'var(--bs-body-color)' },
  ];

  /** The swatch colour for a stored role value (defaults to blue/primary). */
  roleColor(value: unknown): string {
    return this.roleOptions.find((r) => r.value === value)?.color ?? 'var(--bs-primary)';
  }

  // Widget "Icon" field options: a curated set of Bootstrap Icons (self-hosted, no CDN) relevant to
  // energy/solar/battery dashboards, labelled in plain words. The editor shows a live preview swatch.
  protected readonly iconOptions = [
    { value: 'bi-dot', label: 'None' },
    { value: 'bi-sun', label: 'Sun' },
    { value: 'bi-cloud-sun', label: 'Cloud & sun' },
    { value: 'bi-lightning-charge', label: 'Lightning' },
    { value: 'bi-plug', label: 'Plug' },
    { value: 'bi-power', label: 'Power' },
    { value: 'bi-battery', label: 'Battery' },
    { value: 'bi-battery-half', label: 'Battery (half)' },
    { value: 'bi-battery-full', label: 'Battery (full)' },
    { value: 'bi-battery-charging', label: 'Battery (charging)' },
    { value: 'bi-house', label: 'House' },
    { value: 'bi-house-check', label: 'House (check)' },
    { value: 'bi-graph-up', label: 'Graph up' },
    { value: 'bi-graph-down', label: 'Graph down' },
    { value: 'bi-activity', label: 'Activity' },
    { value: 'bi-speedometer2', label: 'Speedometer' },
    { value: 'bi-thermometer-half', label: 'Thermometer' },
    { value: 'bi-heart-pulse', label: 'Heart pulse' },
    { value: 'bi-arrow-repeat', label: 'Cycle' },
    { value: 'bi-pie-chart', label: 'Pie chart' },
    { value: 'bi-piggy-bank', label: 'Piggy bank' },
    { value: 'bi-leaf', label: 'Leaf' },
    { value: 'bi-lightbulb', label: 'Lightbulb' },
    { value: 'bi-clock', label: 'Clock' },
    { value: 'bi-grid-3x3-gap', label: 'Grid' },
  ];

  /** The icon class for a stored icon value (defaults to a neutral dot). */
  iconClass(value: unknown): string {
    return typeof value === 'string' && value ? value : 'bi-dot';
  }

  /** Suggested unit for the widget's chosen metric (shown as the unit field's placeholder). */
  unitHint(w: DashboardWidget): string {
    return metricUnit(typeof w.config['metric'] === 'string' ? (w.config['metric'] as string) : '');
  }
  readonly editing = signal(false);
  readonly configIndex = signal<number | null>(null);

  items: DashboardWidget[] = [];
  private renderedRef: DashboardConfig | null = null;
  private rebuildTimer?: ReturnType<typeof setTimeout>;
  private destroyed = false;

  constructor() {
    // Re-snapshot when a new dashboard object arrives (load or after save/discard reload).
    effect(() => {
      const d = this.dashboard();
      if (d !== this.renderedRef) {
        this.renderedRef = d;
        this.items = d.widgets.map((w) => ({ ...w, config: { ...w.config } }));
        this.editing.set(false);
        this.configIndex.set(null);
        this.rebuild();
      }
    });
  }

  ngAfterViewInit(): void {
    this.init();
  }

  ngOnDestroy(): void {
    this.destroyed = true;
    clearTimeout(this.rebuildTimer);
    this.grid?.destroy(false);
    this.grid = null;
  }

  // --- edit actions ---
  enterEdit(): void {
    this.editing.set(true);
    this.grid?.setStatic(false);
  }

  save(): void {
    this.captureLayout();
    this.editing.set(false);
    this.configIndex.set(null);
    this.grid?.setStatic(true);
    this.layoutSaved.emit(this.items.map((w) => ({ ...w, config: { ...w.config } })));
  }

  discard(): void {
    // Revert the draft to the loaded dashboard and leave edit mode.
    this.items = this.dashboard().widgets.map((w) => ({ ...w, config: { ...w.config } }));
    this.editing.set(false);
    this.configIndex.set(null);
    this.rebuild();
  }

  addWidget(type: string): void {
    const def = widgetDef(type);
    if (!def) return;
    this.captureLayout();
    const y = this.items.reduce((max, w) => Math.max(max, w.y + w.h), 0); // place at the bottom
    this.items = [...this.items, { type, x: 0, y, w: def.defaultW, h: def.defaultH, config: {} }];
    this.configIndex.set(null);
    this.rebuild();
  }

  removeAt(i: number): void {
    this.captureLayout();
    this.items = this.items.filter((_, idx) => idx !== i);
    this.configIndex.set(null);
    this.rebuild();
  }

  configure(i: number): void {
    this.configIndex.set(this.configIndex() === i ? null : i);
  }

  // --- export / import (L06 / T_DB8) ---
  /** Download the current layout as JSON (the DashboardConfig wire format). */
  exportLayout(): void {
    downloadDashboard(this.dashboard());
  }

  /** Replace the layout from a user-supplied JSON file, then persist it via layoutSaved. The
   *  dashboard's own name/id are kept — import swaps the widgets, not the identity. */
  onImportFile(event: Event): void | Promise<void> {
    const input = event.target as HTMLInputElement;
    const file = input.files?.[0];
    if (!file) return;
    return file.text().then((text) => {
      input.value = '';
      let parsed: { name: string; widgets: DashboardWidget[] };
      try {
        parsed = parseDashboard(text);
      } catch {
        this.notice.set({ cls: 'danger', text: "That file isn't a valid dashboard JSON." });
        return;
      }
      // Unknown widget types are a warning, not a hard error — they render a placeholder.
      const unknown = unknownWidgetTypes(parsed.widgets);
      this.items = parsed.widgets.map((w) => ({ ...w, config: { ...w.config } }));
      this.editing.set(false);
      this.configIndex.set(null);
      this.rebuild();
      this.layoutSaved.emit(this.items.map((w) => ({ ...w, config: { ...w.config } })));
      this.notice.set(
        unknown.length
          ? { cls: 'warning', text: `Imported — unknown widget type(s): ${unknown.join(', ')}.` }
          : { cls: 'success', text: 'Layout imported.' },
      );
    });
  }

  // --- config form helpers ---
  configValue(w: DashboardWidget, key: string): unknown {
    return w.config[key] ?? '';
  }

  setConfig(key: string, value: unknown): void {
    const i = this.configIndex();
    if (i === null) return;
    // New config + item object so the widget's ngComponentOutlet inputs recompute.
    const w = this.items[i];
    const config = { ...w.config, [key]: value };
    this.items = this.items.map((it, idx) => (idx === i ? { ...it, config } : it));
  }

  /** Metric dropdown options: live metric keys plus the widget's current value. */
  metricOptions(w: DashboardWidget, key: string): string[] {
    const keys = new Set(Object.keys(this.data().metrics));
    const cur = w.config[key];
    if (typeof cur === 'string' && cur) keys.add(cur);
    return Array.from(keys).sort();
  }

  // --- GridStack lifecycle ---
  private init(): void {
    if (this.grid || this.destroyed) return;
    try {
      this.grid = GridStack.init(
        {
          column: COLUMNS,
          // Responsive: collapse to a single stacked column on narrow (mobile) viewports so
          // widgets stay full-width and readable instead of being crushed into 12 columns.
          columnOpts: { breakpointForWindow: true, breakpoints: [{ w: 768, c: 1 }] },
          cellHeight: this.cellHeight(),
          margin: 6, // px gap between cells (unambiguous; keeps card borders from touching)
          float: true,
          staticGrid: !this.editing(),
        },
        this.gridEl().nativeElement,
      );
      this.grid.on('change', () => this.captureLayout());
    } catch {
      this.grid = null; // headless test env without a layout engine
    }
  }

  private rebuild(): void {
    if (!this.grid) return;
    this.grid.destroy(false);
    this.grid = null;
    // Re-init on a macrotask so Angular has flushed the @for DOM changes first (otherwise
    // GridStack reads a stale child set and a freshly-added widget isn't registered).
    clearTimeout(this.rebuildTimer);
    this.rebuildTimer = setTimeout(() => this.init(), 0);
  }

  /** Sync `items` with GridStack's current node positions (after a drag/resize or before a
   *  structural change), so positions aren't lost. */
  private captureLayout(): void {
    if (!this.grid) return;
    this.items = mergeLayout(this.items, this.grid.save(false) as GridStackNode[]);
  }
}
