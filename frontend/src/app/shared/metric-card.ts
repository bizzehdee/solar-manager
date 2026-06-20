import { Component, input } from '@angular/core';
import { DecimalPipe } from '@angular/common';

// Reusable labelled value + unit card (plan.md §8 component library). Configurable by
// inputs (label/unit/icon/colour role) so the same card serves PV, load, grid, etc.
@Component({
  selector: 'app-metric-card',
  imports: [DecimalPipe],
  template: `<div class="card h-100 overflow-hidden">
    <div class="card-body d-flex align-items-center gap-2 p-2">
      <i class="bi {{ icon() }} fs-3 flex-shrink-0" [class]="'text-' + role()"></i>
      <!-- min-width:0 lets the text column shrink so it truncates instead of overflowing the cell. -->
      <div style="min-width:0">
        <div class="fs-5 fw-semibold text-truncate">
          @if (value() === undefined) { <span class="text-secondary">—</span> }
          @else { {{ value() | number: '1.0-3' }} <small class="text-secondary">{{ unit() }}</small> }
        </div>
        <div class="small text-secondary text-truncate">{{ label() }}</div>
      </div>
    </div>
  </div>`,
})
export class MetricCard {
  readonly label = input.required<string>();
  readonly value = input<number | undefined>(undefined);
  readonly unit = input('');
  readonly icon = input('bi-dot');
  readonly role = input('primary');
}
