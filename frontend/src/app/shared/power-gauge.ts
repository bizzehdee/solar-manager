import { Component, computed, input } from '@angular/core';

// Radial power gauge (plan.md §8) — the same SVG ring as the SoC gauge, but for a power
// value against a full-scale `max` (e.g. inverter rated power). Theme-aware via Bootstrap
// CSS variables, no chart dependency. Bidirectional flows (grid import/export, battery
// charge/discharge) pass the magnitude as `value` and the direction as `sublabel`/`role`.
@Component({
  selector: 'app-power-gauge',
  template: `<div class="text-center">
    <svg viewBox="0 0 120 120" width="150" height="150" role="img" [attr.aria-label]="label()">
      <circle cx="60" cy="60" r="52" fill="none" stroke="var(--bs-border-color)" stroke-width="12" />
      <circle cx="60" cy="60" r="52" fill="none" [attr.stroke]="'var(--bs-' + role() + ')'"
        stroke-width="12" stroke-linecap="round"
        [attr.stroke-dasharray]="circ" [attr.stroke-dashoffset]="offset()"
        transform="rotate(-90 60 60)" />
      <text x="60" y="56" text-anchor="middle" dominant-baseline="middle"
        class="fw-bold" style="font-size:1.25rem" fill="var(--bs-body-color)">{{ valueText() }}</text>
      <text x="60" y="76" text-anchor="middle" style="font-size:.72rem" fill="var(--bs-secondary-color)">
        {{ label() }}</text>
      @if (sublabel()) {
        <text x="60" y="90" text-anchor="middle" style="font-size:.62rem" fill="var(--bs-secondary-color)">
          {{ sublabel() }}</text>
      }
    </svg>
  </div>`,
})
export class PowerGauge {
  /** The value to display + fill the ring with (already a magnitude for bidirectional flows). */
  readonly value = input<number>(0);
  /** Full-scale for the ring (ring caps at 100% if value exceeds it). */
  readonly max = input<number>(8000);
  readonly label = input('');
  readonly sublabel = input('');
  readonly unit = input('W');
  readonly role = input('primary');

  readonly circ = 2 * Math.PI * 52;
  readonly fraction = computed(() => Math.max(0, Math.min(1, Math.abs(this.value()) / (this.max() || 1))));
  readonly offset = computed(() => this.circ * (1 - this.fraction()));

  /** Watts shown as W, or kW (1dp) once ≥ 1000; other units shown as-is. */
  readonly valueText = computed(() => {
    const v = this.value();
    if (this.unit() === 'W' && Math.abs(v) >= 1000) return `${(v / 1000).toFixed(1)} kW`;
    return `${Math.round(v)} ${this.unit()}`;
  });
}
