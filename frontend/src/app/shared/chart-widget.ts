import { Component, DestroyRef, OnDestroy, OnInit, computed, effect, inject, input, signal, untracked } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { catchError, forkJoin, map, of } from 'rxjs';

import { ApiService } from '../core/api.service';
import { HistoryPoint } from '../core/models';
import { metricUnit } from '../core/metric-units';
import { ChartSeries, TimeSeriesChart } from './time-series-chart';

// Unified chart dashboard widget (L06; multi-series L21): a config-driven trend chart for one OR
// MANY metrics over a window ("last N minutes/hours/days"). Each metric is a series in its own
// colour; an optional `stacked` mode draws them as cumulative areas (e.g. PV/battery/grid making up
// load). It fetches `/api/history` per series itself, refreshes on a timer, and refetches on config
// change. Resolution is auto-derived from the window unless pinned. No inline controls — the
// dashboard editor's config modal drives everything.

const UNIT_SECONDS: Record<string, number> = { minutes: 60, hours: 3600, days: 86400 };
const EXPLICIT_RESOLUTIONS = ['raw', '5m', '1h', '1d'];
const REFRESH_MS = 30_000;

interface SeriesConfig {
  metric: string;
  label?: string;
  color?: string;
}

@Component({
  selector: 'app-chart-widget',
  imports: [TimeSeriesChart],
  template: `
    <div class="card h-100">
      <div class="card-body d-flex flex-column p-2">
        <div class="small text-secondary mb-1 text-truncate">{{ heading() }} · last {{ windowText() }}</div>
        <div class="flex-grow-1" style="min-height:0; position:relative">
          @if (loading() && !hasData()) {
            <div class="text-secondary small"><span class="spinner-border spinner-border-sm"></span> Loading…</div>
          } @else if (!hasData()) {
            <div class="text-secondary small">No data yet — history accumulates as samples are recorded.</div>
          } @else {
            <app-time-series-chart
              [series]="seriesData()"
              [stacked]="stacked()"
              [unit]="unit()"
              [kind]="kind()"
            />
          }
        </div>
      </div>
    </div>
  `,
})
export class ChartWidget implements OnInit, OnDestroy {
  private readonly api = inject(ApiService);
  private readonly destroyRef = inject(DestroyRef);
  private destroyed = false;

  /** Widget config: { metrics?: [{metric,label?,color?}], metric?, stacked?, label?, unit?, window?,
   *  window_unit?, resolution? }. Accepts a single `metric` (legacy) and the history-chart `range`. */
  readonly config = input<Record<string, unknown>>({});

  readonly seriesData = signal<ChartSeries[]>([]);
  readonly loading = signal(false);
  readonly hasData = computed(() => this.seriesData().some((s) => s.points.length > 0));
  private readonly availableMetrics = signal<string[]>([]);
  private timer?: ReturnType<typeof setInterval>;

  /** The series to chart: the configured `metrics` list, or a single `metric`, or the first
   *  available metric as a fallback so a freshly-added widget shows something. */
  readonly seriesConfig = computed<SeriesConfig[]>(() => {
    const raw = this.config()['metrics'];
    if (Array.isArray(raw)) {
      const list = raw.map((r) => this.normalizeSeries(r)).filter((s): s is SeriesConfig => !!s);
      if (list.length) return list;
    }
    const single = this.config()['metric'];
    const metric = typeof single === 'string' && single ? single : (this.availableMetrics()[0] ?? '');
    return metric ? [{ metric }] : [];
  });

  readonly stacked = computed(() => this.config()['stacked'] === true);

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
    if (this.config()['window'] === undefined && Number(this.config()['range']) > 0) return 'days';
    return 'hours';
  });
  private readonly windowSeconds = computed(() => this.windowValue() * UNIT_SECONDS[this.windowUnit()]);

  readonly resolution = computed(() => {
    const r = this.config()['resolution'];
    if (typeof r === 'string' && EXPLICIT_RESOLUTIONS.includes(r)) return r;
    const s = this.windowSeconds();
    if (s <= 3 * 3600) return 'raw';
    if (s <= 3 * 86400) return '5m';
    return '1h';
  });

  /** Single-series counters draw as kWh bars (preserving old behaviour); multi-series draws lines. */
  readonly kind = computed<'line' | 'bar'>(() => {
    const cfgs = this.seriesConfig();
    return cfgs.length === 1 && cfgs[0].metric.endsWith('_wh') ? 'bar' : 'line';
  });

  readonly unit = computed(() => {
    const u = this.config()['unit'];
    if (typeof u === 'string' && u) return u;
    const first = this.seriesConfig()[0];
    return first ? metricUnit(first.metric) : '';
  });

  readonly heading = computed(() => {
    const l = this.config()['label'];
    if (typeof l === 'string' && l) return l;
    const cfgs = this.seriesConfig();
    if (cfgs.length === 1) return this.humanise(cfgs[0].metric);
    return cfgs.length ? `${cfgs.length} metrics` : 'Chart';
  });

  readonly windowText = computed(() => `${this.windowValue()} ${this.windowUnit()}`);

  /** A primitive fingerprint of everything a fetch depends on, so the effect refetches only on a
   *  *meaningful* change (the series-config array is a fresh reference each compute, which would
   *  otherwise retrigger on unrelated signal updates). */
  private readonly fetchKey = computed(() =>
    this.seriesConfig().map((s) => s.metric).join('|') + '@' + this.resolution() + '/' + this.windowSeconds(),
  );

  constructor() {
    this.destroyRef.onDestroy(() => (this.destroyed = true));
    this.api
      .getHistoryMetrics()
      .pipe(takeUntilDestroyed())
      .subscribe((res) => this.availableMetrics.set(res.metrics));
    effect(() => {
      this.fetchKey(); // track the fingerprint only
      untracked(() => this.load());
    });
  }

  ngOnInit(): void {
    this.timer = setInterval(() => this.load(), REFRESH_MS);
  }

  ngOnDestroy(): void {
    clearInterval(this.timer);
  }

  private normalizeSeries(row: unknown): SeriesConfig | null {
    if (typeof row === 'string') return row ? { metric: row } : null;
    if (row && typeof row === 'object') {
      const r = row as Record<string, unknown>;
      const metric = typeof r['metric'] === 'string' ? r['metric'] : '';
      if (!metric) return null;
      return {
        metric,
        label: typeof r['label'] === 'string' && r['label'] ? r['label'] : undefined,
        color: typeof r['color'] === 'string' && r['color'] ? r['color'] : undefined,
      };
    }
    return null;
  }

  private load(): void {
    // Never initiate a request after teardown (NG0205).
    if (this.destroyed) return;
    const cfgs = this.seriesConfig();
    if (!cfgs.length) return;
    const resolution = this.resolution();
    const start = Math.floor(Date.now() / 1000) - this.windowSeconds();
    this.loading.set(true);
    forkJoin(
      cfgs.map((c) =>
        this.api.getHistory({ metric: c.metric, resolution, start }).pipe(
          map((res) => res.points),
          catchError(() => of([] as HistoryPoint[])),
        ),
      ),
    )
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (results) => {
          this.seriesData.set(
            results.map((points, i) => {
              const c = cfgs[i];
              const counter = c.metric.endsWith('_wh');
              return {
                label: c.label || this.humanise(c.metric),
                points,
                color: c.color,
                useLast: counter,
                scale: counter ? 1000 : 1,
              };
            }),
          );
          this.loading.set(false);
        },
        error: () => (this.seriesData.set([]), this.loading.set(false)),
      });
  }

  /** Humanise a metric key, e.g. `pv_power_w` → "Pv power". */
  private humanise(metric: string): string {
    if (!metric) return '';
    const words = metric.replace(/_(w|wh|v|hz|c|pct)$/, '').replace(/_/g, ' ').trim();
    return words.charAt(0).toUpperCase() + words.slice(1);
  }
}
