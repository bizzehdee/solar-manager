import { Component, computed, input } from '@angular/core';

import { SettingsField } from '../core/models';

// Read-only rendering of one decoded settings value (plan.md §12 / Phase 5). Pure
// presentational + signal inputs; uses Angular template control-flow (no innerHTML), so
// values are safely interpolated. Bool → Yes/No badge, enum → option label, number/int →
// value + unit, time → "HH:MM" as-is, null/undefined → em-dash.
@Component({
  selector: 'app-setting-value',
  template: `
    @if (value() === null || value() === undefined) {
      <span class="text-secondary">—</span>
    } @else {
      @switch (field().type) {
        @case ('bool') {
          <span class="badge" [class.text-bg-success]="value() === true" [class.text-bg-secondary]="value() !== true">
            {{ value() === true ? 'Yes' : 'No' }}
          </span>
        }
        @case ('enum') { {{ enumLabel() }} }
        @default { {{ scalarText() }} }
      }
    }
  `,
})
export class SettingValue {
  readonly field = input.required<SettingsField>();
  readonly value = input<unknown>(undefined);

  /** Enum machine value → its option label (falls back to the raw value). */
  readonly enumLabel = computed(() => {
    const opt = this.field().options?.find((o) => o.value === this.value());
    return opt ? opt.label : String(this.value());
  });

  /** number/int with a unit appended; time (and unitless numbers) shown as-is. */
  readonly scalarText = computed(() => {
    const f = this.field();
    const v = this.value();
    return f.unit && (f.type === 'number' || f.type === 'int') ? `${v} ${f.unit}` : String(v);
  });
}
