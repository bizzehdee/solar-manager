import { Component, computed, inject, OnInit, signal } from '@angular/core';

import { ApiService } from '../../core/api.service';
import { DailyStats, HistoryPoint } from '../../core/models';
import { StatCard } from '../../shared/stat-card';
import { TimeSeriesChart } from '../../shared/time-series-chart';

// History view (plan.md §9): pick a metric, resolution and range; charts the rolled-up
// time-series. Counters (…_wh) render as kWh bars off the `last` field; gauges as a line.
@Component({
  selector: 'app-history',
  imports: [TimeSeriesChart, StatCard],
  template: `
    <h4 class="mb-3"><i class="bi bi-graph-up"></i> History</h4>

    <!-- Today's KPI row (T053): derived from /api/stats/daily. — for null values. -->
    @if (stats(); as s) {
      <div class="row g-3 mb-3">
        <div class="col-6 col-md-4 col-lg-2">
          <app-stat-card label="Self-consumption" [value]="pct(s.self_consumption_pct)" icon="bi-pie-chart" role="success" />
        </div>
        <div class="col-6 col-md-4 col-lg-2">
          <app-stat-card label="Self-sufficiency" [value]="pct(s.self_sufficiency_pct)" icon="bi-house-check" role="primary" />
        </div>
        <div class="col-6 col-md-4 col-lg-2">
          <app-stat-card label="Savings" [value]="money(s.economics.savings, s.currency)" icon="bi-piggy-bank" role="success" />
        </div>
        <div class="col-6 col-md-4 col-lg-2">
          <app-stat-card label="CO₂ avoided" [value]="kg(s.economics.co2_avoided_kg)" unit="kg" icon="bi-leaf" role="success" />
        </div>
        <div class="col-6 col-md-4 col-lg-2">
          <app-stat-card label="Peak PV" [value]="kw(s.peak_pv_w)" unit="kW" icon="bi-sun" role="warning" />
        </div>
        <div class="col-6 col-md-4 col-lg-2">
          <app-stat-card label="Round-trip eff." [value]="ratioPct(s.round_trip_efficiency)" icon="bi-arrow-repeat" role="info" />
        </div>
      </div>
    }

    <div class="card mb-3">
      <div class="card-body">
        <div class="row g-3 align-items-end">
          <div class="col-12 col-md-5">
            <label class="form-label small text-secondary" for="metric">Metric</label>
            <select id="metric" class="form-select" [value]="metric() ?? ''" (change)="onMetric($event)">
              @if (metrics().length === 0) {
                <option value="">No metrics available</option>
              }
              @for (m of metrics(); track m) {
                <option [value]="m">{{ labelFor(m) }}</option>
              }
            </select>
          </div>
          <div class="col-6 col-md-3">
            <label class="form-label small text-secondary" for="res">Resolution</label>
            <select id="res" class="form-select" [value]="resolution()" (change)="onResolution($event)">
              @for (r of resolutions; track r) {
                <option [value]="r">{{ r }}</option>
              }
            </select>
          </div>
          <div class="col-6 col-md-4">
            <label class="form-label small text-secondary" for="range">Range</label>
            <select id="range" class="form-select" [value]="rangeDays()" (change)="onRange($event)">
              <option [value]="1">Last 24h</option>
              <option [value]="7">Last 7 days</option>
              <option [value]="30">Last 30 days</option>
            </select>
          </div>
        </div>
      </div>
    </div>

    <div class="card">
      <div class="card-body">
        @if (loading()) {
          <div class="text-secondary">
            <span class="spinner-border spinner-border-sm"></span> Loading…
          </div>
        } @else if (points().length === 0) {
          <div class="alert alert-secondary mb-0">
            No data yet — history accumulates as the poller records samples.
          </div>
        } @else {
          <app-time-series-chart
            [points]="points()"
            [label]="labelFor(metric() ?? '')"
            [unit]="unit()"
            [kind]="isCounter() ? 'bar' : 'line'"
            [useLast]="isCounter()"
            [scale]="isCounter() ? 1000 : 1"
          />
        }
      </div>
    </div>
  `,
})
export class HistoryPage implements OnInit {
  private readonly api = inject(ApiService);

  readonly resolutions = ['raw', '5m', '1h', '1d'];

  readonly metrics = signal<string[]>([]);
  readonly metric = signal<string | null>(null);
  readonly resolution = signal('1h');
  readonly rangeDays = signal(1);
  readonly points = signal<HistoryPoint[]>([]);
  readonly loading = signal(false);

  /** Today's daily stats for the KPI row (T053). Null until loaded / on error. */
  readonly stats = signal<DailyStats | null>(null);

  /** Energy counters (…_wh) are accumulating totals — chart `last`, in kWh, as bars. */
  readonly isCounter = computed(() => (this.metric() ?? '').endsWith('_wh'));
  readonly unit = computed(() => this.unitFor(this.metric() ?? ''));

  ngOnInit(): void {
    this.api.getHistoryMetrics().subscribe((res) => {
      this.metrics.set(res.metrics);
      if (res.metrics.length > 0) {
        this.metric.set(res.metrics[0]);
        this.load();
      }
    });
    this.loadStats();
  }

  /** Fetch today's KPIs for the first device (single-inverter rig). Degrade to null on error. */
  private loadStats(): void {
    this.api.getDailyStats().subscribe({
      next: (s) => this.stats.set(s),
      error: () => this.stats.set(null),
    });
  }

  onMetric(e: Event): void {
    this.metric.set((e.target as HTMLSelectElement).value);
    this.load();
  }

  onResolution(e: Event): void {
    this.resolution.set((e.target as HTMLSelectElement).value);
    this.load();
  }

  onRange(e: Event): void {
    this.rangeDays.set(Number((e.target as HTMLSelectElement).value));
    this.load();
  }

  private load(): void {
    const metric = this.metric();
    if (!metric) return;
    const start = Math.floor(Date.now() / 1000) - this.rangeDays() * 86400;
    this.loading.set(true);
    this.api
      .getHistory({ metric, resolution: this.resolution(), start })
      .subscribe({
        next: (res) => {
          this.points.set(res.points);
          this.loading.set(false);
        },
        error: () => {
          this.points.set([]);
          this.loading.set(false);
        },
      });
  }

  /** Humanise a metric key, e.g. `pv_power_w` → "Pv power". */
  labelFor(metric: string): string {
    if (!metric) return '';
    const words = metric.replace(/_(w|wh|v|hz|c|pct)$/, '').replace(/_/g, ' ').trim();
    return words.charAt(0).toUpperCase() + words.slice(1);
  }

  /** Display unit derived from the metric suffix. */
  unitFor(metric: string): string {
    if (metric.endsWith('_wh')) return 'kWh';
    if (metric.endsWith('_w')) return 'W';
    if (metric.endsWith('_v')) return 'V';
    if (metric.endsWith('_hz')) return 'Hz';
    if (metric.endsWith('_c')) return '°C';
    if (metric.endsWith('_pct')) return '%';
    return '';
  }

  // --- KPI formatters (T053). Each returns undefined for null ⇒ stat-card shows "—". ---

  /** A 0..100 percentage value with a `%` suffix. */
  pct(v: number | null): string | undefined {
    return v === null ? undefined : `${v.toFixed(0)}%`;
  }

  /** A 0..1 ratio rendered as a percentage (round-trip efficiency). */
  ratioPct(v: number | null): string | undefined {
    return v === null ? undefined : `${(v * 100).toFixed(0)}%`;
  }

  /** Currency amount, e.g. "GBP 1.23". */
  money(v: number | null, currency: string): string | undefined {
    return v === null ? undefined : `${currency} ${v.toFixed(2)}`;
  }

  /** Kilograms to 1dp. */
  kg(v: number | null): string | undefined {
    return v === null ? undefined : v.toFixed(1);
  }

  /** Watts → kW to 2dp. */
  kw(v: number | null): string | undefined {
    return v === null ? undefined : (v / 1000).toFixed(2);
  }
}
