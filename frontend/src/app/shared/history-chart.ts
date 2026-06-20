import { Component, OnInit, computed, inject, input, signal } from '@angular/core';

import { ApiService } from '../core/api.service';
import { HistoryPoint } from '../core/models';
import { TimeSeriesChart } from './time-series-chart';

// History-chart dashboard widget (L06 / T_DB5): pick a metric/resolution/range and chart the
// rolled-up series. A *container* widget — it owns its selector controls and fetches
// `/api/history` itself (history isn't live-snapshot data), wrapping the dumb
// `<app-time-series-chart>`. Counters (…_wh) render as kWh bars off the `last` field; gauges as a
// line. `config` seeds the initial metric/resolution/range.
@Component({
  selector: 'app-history-chart',
  imports: [TimeSeriesChart],
  template: `
    <div class="card h-100">
      <div class="card-body d-flex flex-column">
        <div class="row g-2 align-items-end mb-3">
          <div class="col-12 col-md-5">
            <label class="form-label small text-secondary" for="hc-metric">Metric</label>
            <select id="hc-metric" class="form-select form-select-sm" [value]="metric() ?? ''" (change)="onMetric($event)">
              @if (metrics().length === 0) {
                <option value="">No metrics available</option>
              }
              @for (m of metrics(); track m) {
                <option [value]="m">{{ labelFor(m) }}</option>
              }
            </select>
          </div>
          <div class="col-6 col-md-3">
            <label class="form-label small text-secondary" for="hc-res">Resolution</label>
            <select id="hc-res" class="form-select form-select-sm" [value]="resolution()" (change)="onResolution($event)">
              @for (r of resolutions; track r) {
                <option [value]="r">{{ r }}</option>
              }
            </select>
          </div>
          <div class="col-6 col-md-3">
            <label class="form-label small text-secondary" for="hc-range">Range</label>
            <select id="hc-range" class="form-select form-select-sm" [value]="rangeDays()" (change)="onRange($event)">
              <option [value]="1">Last 24h</option>
              <option [value]="7">Last 7 days</option>
              <option [value]="30">Last 30 days</option>
            </select>
          </div>
          <div class="col-12 col-md-1 d-grid">
            @if (exportHref(); as href) {
              <a class="btn btn-sm btn-outline-secondary" [href]="href" title="Export this view as CSV">
                <i class="bi bi-download"></i>
              </a>
            }
          </div>
        </div>

        <div class="flex-grow-1">
          @if (loading()) {
            <div class="text-secondary"><span class="spinner-border spinner-border-sm"></span> Loading…</div>
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
    </div>
  `,
})
export class HistoryChart implements OnInit {
  private readonly api = inject(ApiService);

  /** Seeds the initial metric/resolution/range (from the dashboard widget config). */
  readonly config = input<Record<string, unknown>>({});

  readonly resolutions = ['raw', '5m', '1h', '1d'];

  readonly metrics = signal<string[]>([]);
  readonly metric = signal<string | null>(null);
  readonly resolution = signal('1h');
  readonly rangeDays = signal(1);
  readonly points = signal<HistoryPoint[]>([]);
  readonly loading = signal(false);

  readonly isCounter = computed(() => (this.metric() ?? '').endsWith('_wh'));
  readonly unit = computed(() => this.unitFor(this.metric() ?? ''));
  readonly exportHref = computed(() => {
    const m = this.metric();
    if (!m) return null;
    const start = Math.floor(Date.now() / 1000) - this.rangeDays() * 86400;
    return `/api/export?metric=${encodeURIComponent(m)}&resolution=${this.resolution()}&start=${start}`;
  });

  ngOnInit(): void {
    const cfg = this.config();
    if (typeof cfg['resolution'] === 'string') this.resolution.set(cfg['resolution']);
    if (typeof cfg['range'] === 'number') this.rangeDays.set(cfg['range'] as number);
    this.api.getHistoryMetrics().subscribe((res) => {
      this.metrics.set(res.metrics);
      const seed = typeof cfg['metric'] === 'string' ? (cfg['metric'] as string) : null;
      const chosen = seed && res.metrics.includes(seed) ? seed : res.metrics[0];
      if (chosen) {
        this.metric.set(chosen);
        this.load();
      }
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
    this.api.getHistory({ metric, resolution: this.resolution(), start }).subscribe({
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
}
