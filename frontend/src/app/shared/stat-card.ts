import { Component, computed, input } from '@angular/core';

// KPI card for statistics (plan.md §10). Like metric-card, but accepts an already-formatted
// string value (e.g. "92%", "£1.23") so callers can render %/currency without a pipe. Numbers
// are shown as-is. Renders an em-dash for missing values (missing ≠ zero — CLAUDE.md §4).
@Component({
  selector: 'app-stat-card',
  template: `<div class="card h-100">
    <div class="card-body d-flex align-items-center gap-3">
      <i class="bi {{ icon() }} fs-2" [class]="'text-' + role()"></i>
      <div>
        <div class="fs-4 fw-semibold">
          @if (isMissing()) { <span class="text-secondary">—</span> }
          @else { {{ value() }} <small class="text-secondary">{{ unit() }}</small> }
        </div>
        <div class="small text-secondary">{{ label() }}</div>
        @if (hint()) { <div class="small text-secondary fst-italic">{{ hint() }}</div> }
      </div>
    </div>
  </div>`,
})
export class StatCard {
  readonly label = input.required<string>();
  readonly value = input<string | number | undefined | null>(undefined);
  readonly unit = input('');
  readonly icon = input('bi-dot');
  readonly role = input('primary');
  readonly hint = input<string | undefined>(undefined);

  readonly isMissing = computed(() => {
    const v = this.value();
    return v === undefined || v === null;
  });
}
