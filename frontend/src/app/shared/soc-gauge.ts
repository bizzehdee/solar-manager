import { Component, computed, input } from '@angular/core';
import { DecimalPipe } from '@angular/common';

// Radial SoC/percentage gauge (plan.md §8). Pure SVG — no chart dependency — and
// theme-aware via Bootstrap CSS variables. Reusable for any 0–100 value.
@Component({
  selector: 'app-soc-gauge',
  imports: [DecimalPipe],
  template: `<div class="text-center">
    <svg viewBox="0 0 120 120" width="150" height="150" role="img" [attr.aria-label]="label()">
      <circle cx="60" cy="60" r="52" fill="none" stroke="var(--bs-border-color)" stroke-width="12" />
      <circle cx="60" cy="60" r="52" fill="none" [attr.stroke]="'var(--bs-' + role() + ')'"
        stroke-width="12" stroke-linecap="round"
        [attr.stroke-dasharray]="circ" [attr.stroke-dashoffset]="offset()"
        transform="rotate(-90 60 60)" />
      <text x="60" y="60" text-anchor="middle" dominant-baseline="middle"
        class="fw-bold" style="font-size:1.5rem" fill="var(--bs-body-color)">
        {{ value() | number: '1.0-1' }}%</text>
      <text x="60" y="84" text-anchor="middle" style="font-size:.7rem" fill="var(--bs-secondary-color)">
        {{ label() }}</text>
    </svg>
  </div>`,
})
export class SocGauge {
  readonly value = input<number>(0);
  readonly label = input('Battery');

  readonly circ = 2 * Math.PI * 52;
  readonly offset = computed(() => this.circ * (1 - Math.max(0, Math.min(100, this.value())) / 100));
  readonly role = computed(() => {
    const v = this.value();
    return v > 50 ? 'success' : v > 20 ? 'warning' : 'danger';
  });
}
