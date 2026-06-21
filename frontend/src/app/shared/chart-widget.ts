import { Component, OnDestroy, OnInit, computed, effect, inject, input, signal } from '@angular/core';

import { ApiService } from '../core/api.service';
import { HistoryPoint } from '../core/models';
import { metricUnit } from '../core/metric-units';
import { TimeSeriesChart } from './time-series-chart';

// Unified chart dashboard widget (L06): the single config-driven trend chart, merged from the old
// time-series-chart + history-chart (which were near-duplicates). It charts one metric over a
// window ("last N minutes/hours/days"), fetches `/api/history` itself (history isn't live-snapshot
// data), refreshes on a timer so a live dashboard stays current, and refetches whenever its config
// changes. Resolution is auto-derived from the window unless explicitly pinned. Counters (…_wh)
// render as kWh bars off the `last` field; gauges as a line. No inline controls — the dashboard
// editor's config modal drives everything, so view mode is just the chart filling its cell.

const UNIT_SECONDS: Record<string, number> = { minutes: 60, hours: 3600, days: 86400 };
const EXPLICIT_RESOLUTIONS = ['raw', '5m', '1h', '1d'];
const REFRESH_MS = 30_000;

@Component({
  selector: 'app-chart-widget',
  imports: [TimeSeriesChart],
  template: `
    <div class="card h-100">
      <div class="card-body d-flex flex-column p-2">
        <div class="small text-secondary mb-1 text-truncate">{{ heading() }} · last {{ windowText() }}</div>
        <div class="flex-grow-1" style="min-height:0; position:relative">
          @if (loading() && points().length === 0) {
            <div class="text-secondary small"><span class="spinner-border spinner-border-sm"></span> Loading…</div>
          } @else if (points().length === 0) {
            <div class="text-secondary small">No data yet — history accumulates as samples are recorded.</div>
          } @else {
            <app-time-series-chart
              [points]="points()"
              [label]="heading()"
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
export class ChartWidget implements OnInit, OnDestroy {
  private readonly api = inject(ApiService);

  /** Widget config: { metric?, label?, unit?, window?, window_unit?, resolution? }. Also accepts the
   *  legacy history-chart shape ({ resolution, range } in days) for back-compat. */
  readonly config = input<Record<string, unknown>>({});

  readonly points = signal<HistoryPoint[]>([]);
  readonly loading = signal(false);
  private readonly availableMetrics = signal<string[]>([]);
  private timer?: ReturnType<typeof setInterval>;

  /** The configured metric, or the first available one as a fallback. */
  readonly metric = computed(() => {
    const seed = this.config()['metric'];
    if (typeof seed === 'string' && seed) return seed;
    return this.availableMetrics()[0] ?? '';
  });

  private readonly windowValue = computed(() => {
    const w = Number(this.config()['window']);
    if (Number.isFinite(w) && w > 0) return w;
    const r = Number(this.config()['range']); // legacy history-chart range (days)
    if (Number.isFinite(r) && r > 0) return r;
    return 24;
  });
  private readonly windowUnit = computed(() => {
    const u = this.config()['window_unit'];
    if (typeof u === 'string' && u in UNIT_SECONDS) return u;
    // Legacy history-chart expressed its range in days.
    if (this.config()['window'] === undefined && Number(this.config()['range']) > 0) return 'days';
    return 'hours';
  });
  private readonly windowSeconds = computed(() => this.windowValue() * UNIT_SECONDS[this.windowUnit()]);

  /** Bucket size: a pinned config value, else coarser buckets for longer windows. */
  readonly resolution = computed(() => {
    const r = this.config()['resolution'];
    if (typeof r === 'string' && EXPLICIT_RESOLUTIONS.includes(r)) return r;
    const s = this.windowSeconds();
    if (s <= 3 * 3600) return 'raw'; // up to ~3h: raw samples
    if (s <= 3 * 86400) return '5m'; // up to ~3 days
    return '1h';
  });

  readonly isCounter = computed(() => this.metric().endsWith('_wh'));
  readonly unit = computed(() => {
    const u = this.config()['unit'];
    return typeof u === 'string' && u ? u : metricUnit(this.metric());
  });
  readonly heading = computed(() => {
    const l = this.config()['label'];
    return typeof l === 'string' && l ? l : this.humanise(this.metric());
  });
  readonly windowText = computed(() => `${this.windowValue()} ${this.windowUnit()}`);

  constructor() {
    this.api.getHistoryMetrics().subscribe((res) => this.availableMetrics.set(res.metrics));
    // Refetch whenever the resolved metric / resolution / window changes (incl. config edits).
    effect(() => this.load());
  }

  ngOnInit(): void {
    this.timer = setInterval(() => this.load(), REFRESH_MS);
  }

  ngOnDestroy(): void {
    clearInterval(this.timer);
  }

  private load(): void {
    const metric = this.metric();
    const resolution = this.resolution();
    const start = Math.floor(Date.now() / 1000) - this.windowSeconds();
    if (!metric) return;
    this.loading.set(true);
    this.api.getHistory({ metric, resolution, start }).subscribe({
      next: (res) => (this.points.set(res.points), this.loading.set(false)),
      error: () => (this.points.set([]), this.loading.set(false)),
    });
  }

  /** Humanise a metric key, e.g. `pv_power_w` → "Pv power". */
  private humanise(metric: string): string {
    if (!metric) return '';
    const words = metric.replace(/_(w|wh|v|hz|c|pct)$/, '').replace(/_/g, ' ').trim();
    return words.charAt(0).toUpperCase() + words.slice(1);
  }
}
