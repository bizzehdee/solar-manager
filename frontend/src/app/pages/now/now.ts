import { Component, computed, inject } from '@angular/core';

import { LiveService } from '../../core/live.service';
import { MetricValue } from '../../core/models';
import { MetricCard } from '../../shared/metric-card';
import { SocGauge } from '../../shared/soc-gauge';

// "Now" view (plan.md §8): live energy snapshot driven by the WebSocket. A container
// component — it subscribes to LiveService and feeds the presentational gauge/cards.
@Component({
  selector: 'app-now',
  imports: [MetricCard, SocGauge],
  template: `
    <h4 class="mb-3 d-flex align-items-center gap-2">
      Now
      @if (runState(); as rs) {
        <span class="badge text-bg-secondary text-capitalize">{{ rs }}</span>
      }
    </h4>

    <!-- Fault banner (T054): prominent only when the inverter reports active fault codes. -->
    @if (faultCodes().length > 0) {
      <div class="alert alert-danger d-flex align-items-center" role="alert">
        <i class="bi bi-exclamation-triangle-fill me-2"></i>
        <span>Inverter faults: {{ faultCodes().join(', ') }}</span>
      </div>
    }

    @if (metrics(); as m) {
      <div class="row g-3 align-items-stretch">
        <div class="col-12 col-lg-3">
          <div class="card h-100"><div class="card-body d-flex flex-column justify-content-center">
            <app-soc-gauge [value]="num(m['battery_soc_pct']) ?? 0" label="Battery" />
          </div></div>
        </div>
        <div class="col-12 col-lg-9">
          <div class="row g-3">
            <div class="col-6 col-md-3">
              <app-metric-card label="Solar" [value]="num(m['pv_power_w'])" unit="W" icon="bi-sun" role="warning" />
            </div>
            <div class="col-6 col-md-3">
              <app-metric-card label="Load" [value]="num(m['load_power_w'])" unit="W" icon="bi-house" role="primary" />
            </div>
            <div class="col-6 col-md-3">
              <app-metric-card label="Battery" [value]="num(m['battery_power_w'])" unit="W" icon="bi-battery-half" role="success" />
            </div>
            <div class="col-6 col-md-3">
              <app-metric-card [label]="gridLabel()" [value]="gridAbs()" unit="W" icon="bi-plug" [role]="gridRole()" />
            </div>
            <div class="col-6 col-md-3">
              <app-metric-card label="Grid V" [value]="num(m['grid_voltage_v'])" unit="V" icon="bi-lightning" role="info" />
            </div>
            <div class="col-6 col-md-3">
              <app-metric-card label="Grid Hz" [value]="num(m['grid_frequency_hz'])" unit="Hz" icon="bi-activity" role="info" />
            </div>
            <div class="col-6 col-md-3">
              <app-metric-card label="Inverter" [value]="num(m['inverter_temp_c'])" unit="°C" icon="bi-thermometer-half" role="danger" />
            </div>
            <div class="col-6 col-md-3">
              <app-metric-card label="Today solar" [value]="kwh(m['today_pv_wh'])" unit="kWh" icon="bi-graph-up" role="warning" />
            </div>
          </div>
        </div>
      </div>

      <!-- Battery health panel (T055): capability-gated — shown only when SoH or cycles report. -->
      @if (hasBatteryHealth()) {
        <div class="card mt-3">
          <div class="card-header"><i class="bi bi-battery-charging"></i> Battery health</div>
          <div class="card-body">
            <div class="row g-3">
              <div class="col-6 col-md-3">
                <div class="small text-secondary">State of Health</div>
                <div class="fs-5 fw-semibold">{{ fmt(num(m['battery_soh_pct']), '%') }}</div>
              </div>
              <div class="col-6 col-md-3">
                <div class="small text-secondary">Cycles</div>
                <div class="fs-5 fw-semibold">{{ fmt(num(m['battery_cycles']), '') }}</div>
              </div>
              <div class="col-6 col-md-3">
                <div class="small text-secondary">Temperature</div>
                <div class="fs-5 fw-semibold">{{ fmt(num(m['battery_temp_c']), '°C') }}</div>
              </div>
              <div class="col-6 col-md-3">
                <div class="small text-secondary">Voltage</div>
                <div class="fs-5 fw-semibold">{{ fmt(num(m['battery_voltage_v']), 'V') }}</div>
              </div>
            </div>
          </div>
        </div>
      }
    } @else {
      <div class="text-secondary"><span class="spinner-border spinner-border-sm"></span> Waiting for first reading…</div>
    }
  `,
})
export class NowPage {
  private readonly live = inject(LiveService);

  /** Metrics of the first device in the snapshot (single-inverter rig in Phase 0). */
  readonly metrics = computed(() => {
    const snap = this.live.snapshot();
    if (!snap) return null;
    const first = Object.values(snap.devices)[0];
    return first?.metrics ?? null;
  });

  /** Active fault codes (string[]) — empty when absent/healthy. Type-guarded (T054). */
  readonly faultCodes = computed<string[]>(() => {
    const v = this.metrics()?.['inverter_fault_codes'];
    return Array.isArray(v) ? v : [];
  });

  /** Decoded run-state string for the title badge. */
  readonly runState = computed<string | undefined>(() => {
    const v = this.metrics()?.['run_state'];
    return typeof v === 'string' ? v.replace(/_/g, ' ') : undefined;
  });

  /** Battery health is reported when SoH and/or cycle count are present (capability-gated). */
  readonly hasBatteryHealth = computed(() => {
    const m = this.metrics();
    return this.num(m?.['battery_soh_pct']) !== undefined || this.num(m?.['battery_cycles']) !== undefined;
  });

  readonly gridPower = computed(() => this.num(this.metrics()?.['grid_power_w']));
  readonly gridAbs = computed(() => {
    const v = this.gridPower();
    return v === undefined ? undefined : Math.abs(v);
  });
  readonly gridLabel = computed(() => ((this.gridPower() ?? 0) >= 0 ? 'Grid import' : 'Grid export'));
  readonly gridRole = computed(() => ((this.gridPower() ?? 0) >= 0 ? 'danger' : 'info'));

  num(v: MetricValue | undefined): number | undefined {
    return typeof v === 'number' ? v : undefined;
  }
  kwh(v: MetricValue | undefined): number | undefined {
    const n = this.num(v);
    return n === undefined ? undefined : n / 1000;
  }
  /** Render a number with an optional unit, or "—" when missing (missing ≠ zero). */
  fmt(v: number | undefined, unit: string): string {
    if (v === undefined) return '—';
    return unit ? `${v} ${unit}` : `${v}`;
  }
}
