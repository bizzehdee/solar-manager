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
    <h4 class="mb-3">Now</h4>
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
}
