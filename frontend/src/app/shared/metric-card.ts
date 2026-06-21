import { Component, computed, input } from '@angular/core';
import { DecimalPipe } from '@angular/common';

// Reusable labelled value + unit card (plan.md §8/§10 component library), merged from the old
// metric-card + stat-card (which were near-identical). It renders whatever the metric returns:
// numbers are decimal-formatted, strings (e.g. a preformatted "GBP 1.23" or a clock time) are shown
// as-is, and a missing value (undefined/null) shows an em-dash — missing ≠ zero (CLAUDE.md §4).
// Configurable by inputs (label/unit/icon/colour role + optional hint) so one card serves PV, load,
// grid, derived KPIs, forecast times, etc.
@Component({
  selector: 'app-metric-card',
  imports: [DecimalPipe],
  template: `<div class="card h-100 overflow-hidden">
    <div class="card-body d-flex align-items-center gap-2 p-2">
      <i class="bi {{ icon() }} fs-3 flex-shrink-0 text-{{ role() }}"></i>
      <!-- min-width:0 lets the text column shrink so it truncates instead of overflowing the cell. -->
      <div style="min-width:0">
        <div class="fs-5 fw-semibold text-truncate">
          @if (isMissing()) { <span class="text-secondary">—</span> }
          @else if (numeric() !== null) { {{ numeric() | number: '1.0-3' }} <small class="text-secondary">{{ unit() }}</small> }
          @else { {{ display() }} <small class="text-secondary">{{ unit() }}</small> }
        </div>
        <div class="small text-secondary text-truncate">{{ label() }}</div>
        @if (hint()) { <div class="small text-secondary fst-italic text-truncate">{{ hint() }}</div> }
      </div>
    </div>
  </div>`,
})
export class MetricCard {
  readonly label = input.required<string>();
  readonly value = input<number | string | string[] | undefined | null>(undefined);
  readonly unit = input('');
  readonly icon = input('bi-dot');
  readonly role = input('primary');
  readonly hint = input<string | undefined>(undefined);

  readonly isMissing = computed(() => {
    const v = this.value();
    return v === undefined || v === null || (Array.isArray(v) && v.length === 0);
  });

  /** The value as a number when it is one (so it can be decimal-formatted), else null. */
  readonly numeric = computed<number | null>(() => {
    const v = this.value();
    return typeof v === 'number' ? v : null;
  });

  /** Non-numeric display: strings as-is, arrays comma-joined. */
  readonly display = computed<string>(() => {
    const v = this.value();
    if (Array.isArray(v)) return v.join(', ');
    return v == null ? '' : String(v);
  });
}
