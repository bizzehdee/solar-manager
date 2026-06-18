import { Component, OnInit, computed, inject, signal } from '@angular/core';
import { DatePipe } from '@angular/common';

import { ApiService } from '../../core/api.service';
import { LiveService } from '../../core/live.service';
import { DeviceClock, MetricValue } from '../../core/models';
import { MetricCard } from '../../shared/metric-card';
import { SocGauge } from '../../shared/soc-gauge';
import { PowerGauge } from '../../shared/power-gauge';

// "Now" view (plan.md §8): live energy snapshot driven by the WebSocket. A container
// component — it subscribes to LiveService and feeds the presentational gauge/cards.
@Component({
  selector: 'app-now',
  imports: [MetricCard, SocGauge, PowerGauge, DatePipe],
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

      <!-- Inverter clock drift (T097): shown when the device exposes an RTC; Sync gated. -->
      @if (clock(); as c) {
        @if (c.supported) {
          <div class="card mt-3">
            <div class="card-body d-flex align-items-center justify-content-between flex-wrap gap-2 py-2">
              <div class="small">
                <span class="fw-semibold"><i class="bi bi-clock-history"></i> Inverter clock</span>
                <span class="text-secondary ms-2">
                  {{ c.device_time ? (c.device_time | date: 'MMM d, HH:mm:ss') : '—' }} · drift {{ driftLabel(c) }}
                </span>
              </div>
              @if (c.syncable) {
                <button class="btn btn-sm btn-outline-primary" [disabled]="syncingClock()" (click)="syncClock()">
                  <i class="bi bi-arrow-repeat"></i> Sync to system time
                </button>
              } @else {
                <span class="badge text-bg-light">read-only</span>
              }
            </div>
          </div>
        }
      }

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
  // Confirmed max charge current (A) from the device's battery-charging settings; the battery
  // ring scales to it × battery voltage (the inverter's actual charge-power limit).
  private readonly maxChargeCurrentA = signal<number | null>(null);
  private readonly nominalBatteryV = 51.2; // fallback when no live voltage yet (16S LiFePO4)

  readonly solarMax = computed(() => this.pvInstalledW() ?? this.acRatedW());
  readonly batteryMax = computed(() => {
    const a = this.maxChargeCurrentA();
    if (a && a > 0) {
      const v = this.num(this.metrics()?.['battery_voltage_v']);
      return a * (v && v > 0 ? v : this.nominalBatteryV);
    }
    return this.batteryMaxConfiguredW() ?? this.acRatedW();
  });

  // Inverter clock drift (T097), polled with the device fetch.
  readonly clock = signal<DeviceClock | null>(null);
  readonly syncingClock = signal(false);
  private deviceId: string | null = null;

  ngOnInit(): void {
    // Inverter AC rating (load/grid scale) + battery charge-current limit from the device.
    this.api.getDevices().subscribe((res) => {
      const dev = res.devices[0];
      const ac = Number(dev?.ratings?.['ac_power_w']);
      if (Number.isFinite(ac) && ac > 0) this.acRatedW.set(ac);
      if (dev?.id) {
        this.deviceId = dev.id;
        this.api.getDeviceClock(dev.id).subscribe({ next: (c) => this.clock.set(c), error: () => {} });
        this.api.getDeviceSettings(dev.id).subscribe({
          next: (s) => {
            const bc = (s.values?.['battery_charging'] ?? {}) as Record<string, unknown>;
            const a = Number(bc['max_charge_current_a']);
            if (Number.isFinite(a) && a > 0) this.maxChargeCurrentA.set(a);
          },
          error: () => {},
        });
      }
    });
    // Installed PV (Σ kWp) + battery max power fallback from the forecast/site config.
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

  /** Human drift: "in sync" under 1 s, else signed seconds (or minutes when large). */
  driftLabel(c: DeviceClock): string {
    const d = c.drift_s;
    if (d === null) return '—';
    if (Math.abs(d) < 1) return 'in sync';
    const sign = d > 0 ? '+' : '−';
    const abs = Math.abs(d);
    return abs >= 120 ? `${sign}${Math.round(abs / 60)} min` : `${sign}${Math.round(abs)} s`;
  }

  syncClock(): void {
    if (!this.deviceId) return;
    this.syncingClock.set(true);
    this.api.syncDeviceClock(this.deviceId).subscribe({
      next: () => this.api.getDeviceClock(this.deviceId!).subscribe({
        next: (c) => (this.clock.set(c), this.syncingClock.set(false)),
        error: () => this.syncingClock.set(false),
      }),
      error: () => this.syncingClock.set(false),
    });
  }

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
