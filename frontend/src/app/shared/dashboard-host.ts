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
import { WIDGET_REGISTRY, widgetDef } from './widget-registry';

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
    <div class="d-flex flex-wrap gap-2 mb-2 align-items-center">
      @if (!editing()) {
        <button class="btn btn-sm btn-outline-secondary ms-auto" (click)="enterEdit()">
          <i class="bi bi-pencil"></i> Edit
        </button>
      } @else {
        <div class="dropdown">
          <select class="form-select form-select-sm" #addSel (change)="addWidget(addSel.value); addSel.value=''">
            <option value="" selected>+ Add widget…</option>
            @for (t of widgetTypes; track t.type) {
              <option [value]="t.type">{{ t.label }}</option>
            }
          </select>
        </div>
        <button class="btn btn-sm btn-primary ms-auto" (click)="save()"><i class="bi bi-save"></i> Save</button>
        <button class="btn btn-sm btn-outline-secondary" (click)="discard()">Discard</button>
      }
    </div>

    <div class="grid-stack" #grid>
      @for (w of items; track $index) {
        <div class="grid-stack-item" [attr.gs-id]="$index"
             [attr.gs-x]="w.x" [attr.gs-y]="w.y" [attr.gs-w]="w.w" [attr.gs-h]="w.h">
          <div class="grid-stack-item-content position-relative">
            @if (editing()) {
              <div class="widget-edit-overlay position-absolute top-0 end-0 m-1 d-flex gap-1" style="z-index:5">
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
      }
    </div>

    <!-- Inline config panel for the selected widget (T_DB7). -->
    @if (editing() && configIndex() !== null && items[configIndex()!]; as w) {
      <div class="card mt-3">
        <div class="card-header d-flex justify-content-between align-items-center py-2">
          <span><i class="bi bi-gear"></i> Configure {{ defFor(w.type)?.label || w.type }}</span>
          <button class="btn btn-sm btn-outline-secondary" (click)="configIndex.set(null)">Done</button>
        </div>
        <div class="card-body">
          <div class="row g-3">
            @for (f of defFor(w.type)?.configSchema || []; track f.key) {
              <div class="col-12 col-md-4">
                <label class="form-label small text-secondary" [attr.for]="'cfg-' + f.key">{{ f.label }}</label>
                @if (f.type === 'metric') {
                  <select [id]="'cfg-' + f.key" class="form-select form-select-sm"
                          [ngModel]="configValue(w, f.key)" (ngModelChange)="setConfig(f.key, $event)">
                    @for (m of metricOptions(w, f.key); track m) { <option [value]="m">{{ m }}</option> }
                  </select>
                } @else if (f.type === 'number') {
                  <input [id]="'cfg-' + f.key" type="number" class="form-control form-control-sm"
                         [ngModel]="configValue(w, f.key)" (ngModelChange)="setConfig(f.key, $event)" />
                } @else {
                  <input [id]="'cfg-' + f.key" class="form-control form-control-sm"
                         [ngModel]="configValue(w, f.key)" (ngModelChange)="setConfig(f.key, $event)" />
                }
              </div>
            }
          </div>
        </div>
      </div>
    }
  `,
})
export class DashboardHost implements AfterViewInit, OnDestroy {
  readonly dashboard = input.required<DashboardConfig>();
  readonly cellHeight = input('5rem');
  readonly data = input<DashboardData>({ metrics: {} });

  /** Emitted on Save with the edited layout — the page persists it. */
  readonly layoutSaved = output<DashboardWidget[]>();

  private readonly gridEl = viewChild.required<ElementRef<HTMLElement>>('grid');
  private grid: GridStack | null = null;

  protected readonly defFor = widgetDef;
  protected readonly widgetTypes = Object.entries(WIDGET_REGISTRY).map(([type, def]) => ({ type, label: def.label }));
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
          margin: '0.5rem',
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
