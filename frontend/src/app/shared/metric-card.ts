import { Component, input } from '@angular/core';
import { DecimalPipe } from '@angular/common';

// Reusable labelled value + unit card (plan.md §8 component library). Configurable by
// inputs (label/unit/icon/colour role) so the same card serves PV, load, grid, etc.
@Component({
  selector: 'app-metric-card',
  imports: [DecimalPipe],
  template: `<div class="card h-100">
    <div class="card-body d-flex align-items-center gap-3">
      <i class="bi {{ icon() }} fs-2" [class]="'text-' + role()"></i>
      <div>
        <div class="fs-4 fw-semibold">
          @if (value() === undefined) { <span class="text-secondary">—</span> }
          @else { {{ value() | number: '1.0-0' }} <small class="text-secondary">{{ unit() }}</small> }
        </div>
        <div class="small text-secondary">{{ label() }}</div>
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
