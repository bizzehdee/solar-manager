import { Component, OnInit, computed, inject, signal } from '@angular/core';

import { ApiService } from '../../core/api.service';
import { LiveService } from '../../core/live.service';
import { MetricValue } from '../../core/models';
import { MetricCard } from '../../shared/metric-card';
import { SocGauge } from '../../shared/soc-gauge';
import { PowerGauge } from '../../shared/power-gauge';

// "Now" view (plan.md §8): live energy snapshot driven by the WebSocket. A container
// component — it subscribes to LiveService and feeds the presentational gauge/cards.
@Component({
  selector: 'app-now',
  imports: [MetricCard, SocGauge, PowerGauge],
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
      <!-- Live flows as circular gauges (battery SoC + the four power flows). -->
      <div class="row row-cols-2 row-cols-md-3 row-cols-xl-5 g-3 mb-3">
        <div class="col">
          <div class="card h-100"><div class="card-body d-flex justify-content-center align-items-center">
            <app-soc-gauge [value]="num(m['battery_soc_pct']) ?? 0" label="Battery SoC" />
          </div></div>
        </div>
        <div class="col">
          <div class="card h-100"><div class="card-body d-flex justify-content-center align-items-center">
            <app-power-gauge [value]="num(m['pv_power_w']) ?? 0" [max]="solarMax()" label="Solar" role="warning" />
          </div></div>
        </div>
        <div class="col">
          <div class="card h-100"><div class="card-body d-flex justify-content-center align-items-center">
            <app-power-gauge [value]="num(m['load_power_w']) ?? 0" [max]="acRatedW()" label="Load" role="primary" />
          </div></div>
        </div>
        <div class="col">
          <div class="card h-100"><div class="card-body d-flex justify-content-center align-items-center">
            <app-power-gauge [value]="batteryAbs() ?? 0" [max]="batteryMax()" label="Battery"
              [sublabel]="batteryDir()" [role]="batteryRole()" />
          </div></div>
        </div>
        <div class="col">
          <div class="card h-100"><div class="card-body d-flex justify-content-center align-items-center">
            <app-power-gauge [value]="gridAbs() ?? 0" [max]="acRatedW()" label="Grid"
              [sublabel]="gridDir()" [role]="gridRole()" />
          </div></div>
        </div>
      </div>

      <!-- Secondary instantaneous readings. -->
      <div class="row g-3">
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
export class NowPage implements OnInit {
  private readonly live = inject(LiveService);
  private readonly api = inject(ApiService);

  // Gauge full-scales from the actual installation (not a flat default): inverter rated AC
  // power for load/grid, installed PV (Σ array kWp) for solar, and battery max charge/
  // discharge for the battery. Rings cap at 100% if a flow exceeds its scale, but the gauge
  // still shows the real value. Fall back to 8 kW until config loads.
  readonly acRatedW = signal(8000);
  private readonly pvInstalledW = signal<number | null>(null);
  private readonly batteryMaxConfiguredW = signal<number | null>(null);
  readonly solarMax = computed(() => this.pvInstalledW() ?? this.acRatedW());
  readonly batteryMax = computed(() => this.batteryMaxConfiguredW() ?? this.acRatedW());

  ngOnInit(): void {
    // Inverter AC rating (load/grid scale) from the active device's ratings.
    this.api.getDevices().subscribe((res) => {
      const ac = Number(res.devices[0]?.ratings?.['ac_power_w']);
      if (Number.isFinite(ac) && ac > 0) this.acRatedW.set(ac);
    });
    // Installed PV (Σ kWp) + battery max power from the forecast/site config.
    this.api.getForecastConfig().subscribe((cfg) => {
      const pv = (cfg.arrays ?? []).reduce((sum, a) => sum + (a.kwp ?? 0) * 1000, 0);
      if (pv > 0) this.pvInstalledW.set(pv);
      const b = cfg.battery;
      const bm = Math.max(b?.max_charge_w ?? 0, b?.max_discharge_w ?? 0);
      if (bm > 0) this.batteryMaxConfiguredW.set(bm);
    });
  }

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

  // Grid: + = importing (drawing from grid), − = exporting (selling). Magnitude on the ring.
  readonly gridPower = computed(() => this.num(this.metrics()?.['grid_power_w']));
  readonly gridAbs = computed(() => {
    const v = this.gridPower();
    return v === undefined ? undefined : Math.abs(v);
  });
  readonly gridDir = computed(() => {
    const v = this.gridPower();
    if (v === undefined || Math.abs(v) < 1) return 'idle';
    return v > 0 ? 'importing' : 'exporting';
  });
  readonly gridRole = computed(() => ((this.gridPower() ?? 0) >= 0 ? 'danger' : 'info'));

  // Battery: + = charging, − = discharging. Magnitude on the ring.
  readonly batteryPower = computed(() => this.num(this.metrics()?.['battery_power_w']));
  readonly batteryAbs = computed(() => {
    const v = this.batteryPower();
    return v === undefined ? undefined : Math.abs(v);
  });
  readonly batteryDir = computed(() => {
    const v = this.batteryPower();
    if (v === undefined || Math.abs(v) < 1) return 'idle';
    return v > 0 ? 'charging' : 'discharging';
  });
  readonly batteryRole = computed(() => {
    const v = this.batteryPower() ?? 0;
    if (Math.abs(v) < 1) return 'secondary';
    return v > 0 ? 'success' : 'warning';
  });

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
