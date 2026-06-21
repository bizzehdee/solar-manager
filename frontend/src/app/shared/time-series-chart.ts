import { Component, computed, input } from '@angular/core';
import { ChartConfiguration, ChartData, ChartType } from 'chart.js';
import { BaseChartDirective } from 'ng2-charts';

import { HistoryPoint } from '../core/models';

/** One series in a multi-series chart (L21): a metric's points + how to draw it. */
export interface ChartSeries {
  label: string;
  points: HistoryPoint[];
  color?: string;      // hex; falls back to the palette by index
  useLast?: boolean;   // pick `last` (counters) instead of `value`
  scale?: number;      // divide y-values (e.g. Wh → kWh)
}

// Distinct, colour-blind-friendlier defaults assigned to series without an explicit colour.
const SERIES_PALETTE = [
  '#0d6efd', '#198754', '#fd7e14', '#dc3545', '#6f42c1',
  '#0dcaf0', '#ffc107', '#6c757d', '#20c997', '#d63384',
];

// Reusable time-series chart (plan.md §9). Wraps ng2-charts' BaseChartDirective.
// Two modes: a single series (`points` + `label`, with an optional right-axis `overlay`, used by the
// Forecast page) OR multiple series (`series`, used by the chart widget) — each a different colour,
// optionally `stacked` (cumulative areas). NOTE: chart.js' time scale needs a date adapter we
// deliberately don't install (no-CDN/offline rule), so we pre-format x labels and feed a category axis.
@Component({
  selector: 'app-time-series-chart',
  imports: [BaseChartDirective],
  // Fill the host exactly at any size. The canvas is absolutely positioned so it never feeds its own
  // size back into the layout (the classic chart.js "won't shrink / scrollbar" trap).
  styles: [`
    :host { display: block; width: 100%; height: 100%; }
    .tsc-wrap { position: relative; width: 100%; height: 100%; overflow: hidden; }
    .tsc-wrap canvas { position: absolute; inset: 0; }
  `],
  template: `<div class="tsc-wrap">
    <canvas
      baseChart
      [type]="kind()"
      [data]="data()"
      [options]="options()"
    ></canvas>
  </div>`,
})
export class TimeSeriesChart {
  // --- single-series API (Forecast) ---
  readonly points = input<HistoryPoint[]>([]);
  readonly label = input('');
  readonly unit = input('');
  readonly kind = input<'line' | 'bar'>('line');
  /** Pick the `last` field (counters) instead of `value` (gauges). */
  readonly useLast = input(false);
  /** Optional override; defaults to the theme primary colour. */
  readonly color = input<string | undefined>(undefined);
  /** Divide y-values by this for display (e.g. Wh → kWh). */
  readonly scale = input(1);
  /** Fixed bounds for the primary (left) Y axis; auto when omitted (e.g. 0/100 for SoC %). */
  readonly yMin = input<number | undefined>(undefined);
  readonly yMax = input<number | undefined>(undefined);
  /** Floor for the primary axis' top value — the axis grows past it if data exceeds it. */
  readonly ySuggestedMax = input<number | undefined>(undefined);

  // --- multi-series API (chart widget) ---
  /** When non-empty, draws these instead of the single series — one dataset each, different colours. */
  readonly series = input<ChartSeries[]>([]);
  /** Stack the series cumulatively (filled areas / stacked bars). */
  readonly stacked = input(false);

  // Optional second series drawn as a line on a right-hand Y axis (single-series mode only).
  readonly overlayPoints = input<HistoryPoint[] | undefined>(undefined);
  readonly overlayLabel = input('');
  readonly overlayUnit = input('');
  readonly overlayColor = input('#6c757d');
  readonly overlayMin = input<number | undefined>(undefined);
  readonly overlayMax = input<number | undefined>(undefined);

  private readonly stroke = computed(() => this.color() ?? SERIES_PALETTE[0]);
  private readonly hasOverlay = computed(() => (this.overlayPoints()?.length ?? 0) > 0);
  private readonly multi = computed(() => this.series().length > 0);

  readonly data = computed<ChartData<ChartType, (number | null)[], string>>(() =>
    this.multi() ? this.multiData() : this.singleData(),
  );

  /** Multiple series aligned on the union of their timestamps (rollup buckets line up; gaps → null). */
  private multiData(): ChartData<ChartType, (number | null)[], string> {
    const series = this.series();
    const stacked = this.stacked();
    const tsSet = new Set<number>();
    for (const s of series) for (const p of s.points) tsSet.add(p.ts);
    const tsList = [...tsSet].sort((a, b) => a - b);
    const labels = tsList.map((ts) => this.fmtTime(ts));
    const datasets = series.map((s, i) => {
      const div = s.scale || 1;
      const byTs = new Map(s.points.map((p) => [p.ts, (s.useLast ? (p.last ?? p.value) : p.value) / div]));
      const c = s.color || SERIES_PALETTE[i % SERIES_PALETTE.length];
      return {
        data: tsList.map((ts) => (byTs.has(ts) ? byTs.get(ts)! : null)),
        label: s.label,
        borderColor: c,
        backgroundColor: this.kind() === 'bar' || stacked ? (stacked ? this.alpha(c) : c) : this.alpha(c),
        pointRadius: 0,
        borderWidth: 2,
        fill: stacked,
        tension: 0.2,
        ...(stacked ? { stack: 'stack' } : {}),
      };
    });
    return { labels, datasets };
  }

  private singleData(): ChartData<ChartType, (number | null)[], string> {
    const pts = this.points();
    const useLast = this.useLast();
    const div = this.scale() || 1;
    const labels = pts.map((p) => this.fmtTime(p.ts));
    const values = pts.map((p) => (useLast ? (p.last ?? p.value) : p.value) / div);
    const c = this.stroke();
    const datasets: ChartData<ChartType, (number | null)[], string>['datasets'] = [
      {
        data: values,
        label: this.label(),
        yAxisID: 'y',
        borderColor: c,
        backgroundColor: this.kind() === 'bar' ? c : this.alpha(c),
        pointRadius: 0,
        borderWidth: 2,
        fill: this.kind() === 'line',
        tension: 0.2,
      },
    ];

    const overlay = this.overlayPoints();
    if (overlay && overlay.length) {
      const oc = this.overlayColor();
      datasets.push({
        type: 'line',
        data: overlay.map((p) => p.value),
        label: this.overlayLabel(),
        yAxisID: 'y1',
        borderColor: oc,
        backgroundColor: this.alpha(oc),
        pointRadius: 0,
        borderWidth: 1.5,
        borderDash: [4, 3],
        fill: false,
        tension: 0.2,
      });
    }
    return { labels, datasets };
  }

  readonly options = computed<ChartConfiguration['options']>(() => {
    const unit = this.unit();
    const overlayUnit = this.overlayUnit();
    const hasOverlay = this.hasOverlay();
    const stacked = this.stacked();
    const showLegend = hasOverlay || this.series().length > 1;
    return {
      responsive: true,
      maintainAspectRatio: false,
      animation: false,
      plugins: {
        legend: { display: showLegend },
        tooltip: {
          callbacks: {
            label: (ctx) => {
              const u = ctx.datasetIndex === 1 && hasOverlay ? overlayUnit : unit;
              const name = ctx.dataset.label ? `${ctx.dataset.label}: ` : '';
              return `${name}${ctx.formattedValue}${u ? ' ' + u : ''}`;
            },
          },
        },
      },
      scales: {
        x: {
          stacked,
          ticks: { maxRotation: 0, autoSkip: true, maxTicksLimit: 8 },
          grid: { display: false },
        },
        y: {
          stacked,
          beginAtZero: stacked,
          min: this.yMin(),
          max: this.yMax(),
          suggestedMax: this.ySuggestedMax(),
          title: { display: !!unit, text: unit },
        },
        ...(hasOverlay
          ? {
              y1: {
                position: 'right' as const,
                beginAtZero: false,
                min: this.overlayMin(),
                max: this.overlayMax(),
                title: { display: !!overlayUnit, text: overlayUnit },
                grid: { drawOnChartArea: false },
              },
            }
          : {}),
      },
    };
  });

  /** Localised hh:mm (or short date for daily rollups). */
  private fmtTime(tsSeconds: number): string {
    const d = new Date(tsSeconds * 1000);
    return d.toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
  }

  /** Translucent fill colour for line/area charts. */
  private alpha(c: string): string {
    if (c.startsWith('#') && c.length === 7) return c + '33';
    return c;
  }
}
