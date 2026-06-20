import { NgComponentOutlet } from '@angular/common';
import {
  AfterViewInit,
  Component,
  ElementRef,
  OnDestroy,
  effect,
  input,
  output,
  viewChild,
} from '@angular/core';
import { GridStack, GridStackNode } from 'gridstack';

import { DashboardConfig, DashboardData, DashboardWidget } from '../core/models';
import { widgetDef } from './widget-registry';

// Pure layout host for L06 dashboards (T_DB2). Loads a DashboardConfig, lays its widgets out on a
// 12-column GridStack, and — in edit mode — lets the user drag/resize, emitting the updated layout.
// Deliberately knows *nothing* about widgets: it renders a placeholder per cell; T_DB3 swaps in the
// widget registry. GridStack mutates the DOM directly, so the item list is snapshotted from the
// input once per dashboard and never re-rendered by Angular while GridStack owns it.

const COLUMNS = 12;

/** Map GridStack's saved nodes back onto the original widgets (type/config preserved), using the
 *  `gs-id` we stamped as the widget's index. Pure + exported so it's unit-testable without a DOM. */
export function mergeLayout(widgets: DashboardWidget[], nodes: GridStackNode[]): DashboardWidget[] {
  return nodes
    .map((n) => {
      const orig = widgets[Number(n.id)];
      if (!orig) return null;
      return {
        ...orig,
        x: n.x ?? orig.x,
        y: n.y ?? orig.y,
        w: n.w ?? orig.w,
        h: n.h ?? orig.h,
      };
    })
    .filter((w): w is DashboardWidget => w !== null)
    .sort((a, b) => a.y - b.y || a.x - b.x);
}

@Component({
  selector: 'app-dashboard-host',
  imports: [NgComponentOutlet],
  template: `
    <div class="grid-stack" #grid>
      @for (w of items; track $index) {
        <div
          class="grid-stack-item"
          [attr.gs-id]="$index"
          [attr.gs-x]="w.x"
          [attr.gs-y]="w.y"
          [attr.gs-w]="w.w"
          [attr.gs-h]="w.h"
        >
          <div class="grid-stack-item-content">
            @if (defFor(w.type); as def) {
              <ng-container *ngComponentOutlet="def.component; inputs: def.inputs(w.config, data())" />
            } @else {
              <div class="card h-100">
                <div class="card-body d-flex align-items-center justify-content-center text-secondary small">
                  Unknown widget: {{ w.type }}
                </div>
              </div>
            }
          </div>
        </div>
      }
    </div>
  `,
})
export class DashboardHost implements AfterViewInit, OnDestroy {
  readonly dashboard = input.required<DashboardConfig>();
  /** Edit mode: drag + resize enabled. View mode (default): the grid is static. */
  readonly editable = input(false);
  /** Cell height as a rem-based unit so rows track Bootstrap's spacing scale. */
  readonly cellHeight = input('5rem');

  /** Live data fed to each widget via the registry's `inputs(config, data)` adapter. */
  readonly data = input<DashboardData>({ metrics: {} });

  /** Emitted (in edit mode) whenever the user moves/resizes a widget. */
  readonly layoutChange = output<DashboardWidget[]>();

  /** Registry lookup for the template — `undefined` ⇒ render the unknown-widget placeholder. */
  protected readonly defFor = widgetDef;

  private readonly gridEl = viewChild.required<ElementRef<HTMLElement>>('grid');
  private grid: GridStack | null = null;

  /** Snapshot of the widgets currently rendered — taken per dashboard, not re-bound during edits. */
  items: DashboardWidget[] = [];
  private renderedId: string | null = null;

  constructor() {
    // Re-snapshot only when the dashboard identity changes (a new layout to lay out).
    effect(() => {
      const d = this.dashboard();
      if (d.id !== this.renderedId) {
        this.renderedId = d.id;
        this.items = d.widgets.map((w) => ({ ...w }));
        this.rebuild();
      }
    });
    // Toggle static/interactive as edit mode flips, without rebuilding.
    effect(() => {
      const editable = this.editable();
      this.grid?.setStatic(!editable);
    });
  }

  ngAfterViewInit(): void {
    this.init();
  }

  ngOnDestroy(): void {
    this.grid?.destroy(false);
    this.grid = null;
  }

  private init(): void {
    if (this.grid) return;
    try {
      this.grid = GridStack.init(
        {
          column: COLUMNS,
          cellHeight: this.cellHeight(),
          margin: '0.5rem',
          float: true,
          staticGrid: !this.editable(),
        },
        this.gridEl().nativeElement,
      );
      this.grid.on('change', () => this.emitLayout());
    } catch {
      // GridStack needs a real layout engine (ResizeObserver/getComputedStyle); in headless
      // unit tests it may be unavailable. The placeholder markup still renders + is testable.
      this.grid = null;
    }
  }

  /** Re-create the GridStack from the current `items` (after Angular has rendered them). */
  private rebuild(): void {
    if (!this.grid) return;
    this.grid.destroy(false);
    this.grid = null;
    // Defer so Angular flushes the @for before GridStack re-reads the DOM.
    queueMicrotask(() => this.init());
  }

  private emitLayout(): void {
    if (!this.grid) return;
    const nodes = this.grid.save(false) as GridStackNode[];
    this.layoutChange.emit(mergeLayout(this.items, nodes));
  }
}
