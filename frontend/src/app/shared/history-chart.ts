import { Component, computed, effect, inject, input, signal } from '@angular/core';

import { ApiService } from '../core/api.service';
import { HistoryPoint } from '../core/models';
import { metricUnit } from '../core/metric-units';
import { TimeSeriesChart } from './time-series-chart';

// History-chart dashboard widget (L06 / T_DB5): charts a rolled-up metric series. Fully
// config-driven — metric/resolution/range come from the widget config (set via the dashboard
// editor's config modal), so there are no inline controls and view mode shows just the chart, which
// fills the cell. It fetches `/api/history` itself (history isn't live-snapshot data) and refetches
// whenever the config changes. Counters (…_wh) render as kWh bars off `last`; gauges as a line.
@Component({
  selector: 'app-history-chart',
  imports: [TimeSeriesChart],
  template: `
    <div class="card h-100">
      <div class="card-body d-flex flex-column p-2">
        <div class="flex-grow-1" style="min-height:0; position:relative">
          @if (loading() && points().length === 0) {
            <div class="text-secondary small"><span class="spinner-border spinner-border-sm"></span> Loading…</div>
          } @else if (points().length === 0) {
            <div class="text-secondary small">No data yet — history accumulates as the poller records samples.</div>
          } @else {
            <app-time-series-chart
              [points]="points()"
              [label]="labelFor(metric())"
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
export class HistoryChart {
  private readonly api = inject(ApiService);

  /** Widget config: { metric, resolution, range }. */
  readonly config = input<Record<string, unknown>>({});

  readonly points = signal<HistoryPoint[]>([]);
  readonly loading = signal(false);
  private readonly availableMetrics = signal<string[]>([]);

  readonly resolution = computed(() => {
    const r = this.config()['resolution'];
    return typeof r === 'string' && r ? r : '1h';
  });
  readonly rangeDays = computed(() => {
    const n = Number(this.config()['range']);
    return Number.isFinite(n) && n > 0 ? n : 1;
  });
  /** The configured metric, or the first available one as a fallback. */
  readonly metric = computed(() => {
    const seed = this.config()['metric'];
    if (typeof seed === 'string' && seed) return seed;
    return this.availableMetrics()[0] ?? '';
  });

  readonly isCounter = computed(() => this.metric().endsWith('_wh'));
  readonly unit = computed(() => metricUnit(this.metric()));

  constructor() {
    this.api.getHistoryMetrics().subscribe((res) => this.availableMetrics.set(res.metrics));
    // Refetch whenever the resolved metric / resolution / range changes (incl. config edits).
    effect(() => {
      const metric = this.metric();
      const resolution = this.resolution();
      const start = Math.floor(Date.now() / 1000) - this.rangeDays() * 86400;
      if (!metric) return;
      this.loading.set(true);
      this.api.getHistory({ metric, resolution, start }).subscribe({
        next: (res) => (this.points.set(res.points), this.loading.set(false)),
        error: () => (this.points.set([]), this.loading.set(false)),
      });
    });
  }

  /** Humanise a metric key, e.g. `pv_power_w` → "Pv power". */
  labelFor(metric: string): string {
    if (!metric) return '';
    const words = metric.replace(/_(w|wh|v|hz|c|pct)$/, '').replace(/_/g, ' ').trim();
    return words.charAt(0).toUpperCase() + words.slice(1);
  }
}
