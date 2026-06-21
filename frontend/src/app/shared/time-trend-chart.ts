import { Component, OnDestroy, OnInit, computed, inject, input, signal } from '@angular/core';

import { ApiService } from '../core/api.service';
import { HistoryPoint } from '../core/models';
import { metricUnit } from '../core/metric-units';
import { TimeSeriesChart } from './time-series-chart';

// Time-series dashboard widget (L06): a *configured* trend chart for one metric over a fixed
// window ("last N minutes/hours/days"). Unlike the interactive history-chart, it has no selectors —
// the dashboard editor sets metric + window once. It fetches `/api/history` for the window (history
// isn't live-snapshot data) and refreshes on a timer so a live dashboard stays current. Counters
// (…_wh) render as kWh bars off the `last` field; gauges as a line.

const UNIT_SECONDS: Record<string, number> = { minutes: 60, hours: 3600, days: 86400 };
const REFRESH_MS = 30_000;

@Component({
  selector: 'app-time-trend-chart',
  imports: [TimeSeriesChart],
  template: `
    <div class="card h-100">
      <div class="card-body d-flex flex-column p-2">
        <div class="small text-secondary mb-1 text-truncate">{{ label() }} · last {{ windowText() }}</div>
        <div class="flex-grow-1" style="min-height:0; position:relative">
          @if (loading() && points().length === 0) {
            <div class="text-secondary small"><span class="spinner-border spinner-border-sm"></span> Loading…</div>
          } @else if (points().length === 0) {
            <div class="text-secondary small">No data yet — history accumulates as samples are recorded.</div>
          } @else {
            <app-time-series-chart
              [points]="points()"
              [label]="label()"
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
export class TimeTrendChart implements OnInit, OnDestroy {
  private readonly api = inject(ApiService);

  /** Dashboard widget config: { metric, label?, unit?, window?, window_unit? }. */
  readonly config = input<Record<string, unknown>>({});

  readonly points = signal<HistoryPoint[]>([]);
  readonly loading = signal(false);
  private timer?: ReturnType<typeof setInterval>;

  private readonly metric = computed(() => (typeof this.config()['metric'] === 'string' ? (this.config()['metric'] as string) : ''));
  private readonly windowValue = computed(() => {
    const v = Number(this.config()['window']);
    return Number.isFinite(v) && v > 0 ? v : 60;
  });
  private readonly windowUnit = computed(() => {
    const u = String(this.config()['window_unit'] ?? 'minutes');
    return u in UNIT_SECONDS ? u : 'minutes';
  });
  private readonly windowSeconds = computed(() => this.windowValue() * UNIT_SECONDS[this.windowUnit()]);

  readonly isCounter = computed(() => this.metric().endsWith('_wh'));
  readonly label = computed(() => (typeof this.config()['label'] === 'string' && this.config()['label'] ? (this.config()['label'] as string) : this.humanise(this.metric())));
  readonly unit = computed(() => (typeof this.config()['unit'] === 'string' && this.config()['unit'] ? (this.config()['unit'] as string) : metricUnit(this.metric())));
  readonly windowText = computed(() => `${this.windowValue()} ${this.windowUnit()}`);

  /** Coarser buckets for longer windows so we don't pull thousands of raw points. */
  private readonly resolution = computed(() => {
    const s = this.windowSeconds();
    if (s <= 3 * 3600) return 'raw'; // up to ~3h: raw samples
    if (s <= 3 * 86400) return '5m'; // up to ~3 days
    return '1h';
  });

  ngOnInit(): void {
    this.load();
    this.timer = setInterval(() => this.load(), REFRESH_MS);
  }

  ngOnDestroy(): void {
    clearInterval(this.timer);
  }

  private load(): void {
    const metric = this.metric();
    if (!metric) return;
    const start = Math.floor(Date.now() / 1000) - this.windowSeconds();
    this.loading.set(true);
    this.api.getHistory({ metric, resolution: this.resolution(), start }).subscribe({
      next: (res) => (this.points.set(res.points), this.loading.set(false)),
      error: () => this.loading.set(false),
    });
  }

  private humanise(metric: string): string {
    if (!metric) return '';
    const words = metric.replace(/_(w|wh|v|hz|c|pct)$/, '').replace(/_/g, ' ').trim();
    return words.charAt(0).toUpperCase() + words.slice(1);
  }

}
