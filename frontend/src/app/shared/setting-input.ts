import { Component, computed, input, output } from '@angular/core';

import { SettingsField } from '../core/models';

// Editable counterpart to <app-setting-value> (plan.md §12 / Phase 6). Schema-driven, so it
// renders the right native control for the field's decoded type and emits a typed value:
// bool → checkbox (boolean), enum → select (machine int), number/int → number input (honours
// min/max), time → time input ("HH:MM"). No innerHTML — Angular template control-flow only.
@Component({
  selector: 'app-setting-input',
  template: `
    @switch (field().type) {
      @case ('bool') {
        <div class="form-check mb-0">
          <input
            class="form-check-input"
            type="checkbox"
            [checked]="value() === true"
            [attr.aria-label]="field().label"
            (change)="onBool($event)"
          />
        </div>
      }
      @case ('enum') {
        <select class="form-select form-select-sm" [attr.aria-label]="field().label" (change)="onEnum($event)">
          @for (o of field().options ?? []; track o.value) {
            <option [value]="o.value" [selected]="o.value === value()">{{ o.label }}</option>
          }
        </select>
      }
      @case ('time') {
        <input
          class="form-control form-control-sm"
          type="time"
          [value]="asString()"
          [attr.aria-label]="field().label"
          (change)="onText($event)"
        />
      }
      @default {
        <input
          class="form-control form-control-sm"
          type="number"
          [value]="asString()"
          [min]="field().min ?? null"
          [max]="field().max ?? null"
          [attr.aria-label]="field().label"
          (input)="onNumber($event)"
        />
      }
    }
  `,
})
export class SettingInput {
  readonly field = input.required<SettingsField>();
  readonly value = input<unknown>(undefined);
  readonly valueChange = output<unknown>();

  readonly asString = computed(() => {
    const v = this.value();
    return v === null || v === undefined ? '' : String(v);
  });

  onBool(e: Event): void {
    this.valueChange.emit((e.target as HTMLInputElement).checked);
  }

  onEnum(e: Event): void {
    this.valueChange.emit(Number((e.target as HTMLSelectElement).value));
  }

  onText(e: Event): void {
    this.valueChange.emit((e.target as HTMLInputElement).value);
  }

  onNumber(e: Event): void {
    const raw = (e.target as HTMLInputElement).value;
    this.valueChange.emit(raw === '' ? null : Number(raw));
  }
}
