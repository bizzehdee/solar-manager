import { Component, computed, input } from '@angular/core';
import { ChartConfiguration, ChartData, ChartType } from 'chart.js';
import { BaseChartDirective } from 'ng2-charts';

import { HistoryPoint } from '../core/models';

// Reusable time-series chart (plan.md §9). Wraps ng2-charts' BaseChartDirective.
// NOTE: chart.js' time scale needs a date adapter that we deliberately do NOT install
// (no-CDN/offline rule), so we pre-format x labels to strings and feed numeric `data`
// arrays into a category axis rather than {x,y} time-scale points.
@Component({
  selector: 'app-time-series-chart',
  imports: [BaseChartDirective],
  // Fill the host exactly at any size. The canvas is absolutely positioned so it never feeds its own
  // size back into the layout (the classic chart.js "won't shrink / scrollbar" trap); chart.js is
  // responsive + maintainAspectRatio:false, so it tracks the wrapper as the cell is resized.
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
  readonly points = input.required<HistoryPoint[]>();
  readonly label = input.required<string>();
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
  /** Floor for the primary axis' top value — the axis grows past it if data exceeds it,
   *  but never shrinks below it (e.g. installed array watts, so a cloudy day still reads
   *  small against full capacity). */
  readonly ySuggestedMax = input<number | undefined>(undefined);

  // Optional second series drawn as a line on a right-hand Y axis (e.g. cloud cover %
  // over expected PV). Sharing the x labels of `points`, it's aligned by index.
  readonly overlayPoints = input<HistoryPoint[] | undefined>(undefined);
  readonly overlayLabel = input('');
  readonly overlayUnit = input('');
  readonly overlayColor = input('#6c757d');
  /** Fixed bounds for the overlay axis (e.g. 0/100 for a percentage); auto when omitted. */
  readonly overlayMin = input<number | undefined>(undefined);
  readonly overlayMax = input<number | undefined>(undefined);

  private readonly stroke = computed(() => this.color() ?? '#0d6efd');
  private readonly hasOverlay = computed(() => (this.overlayPoints()?.length ?? 0) > 0);

  readonly data = computed<ChartData<ChartType, number[], string>>(() => {
    const pts = this.points();
    const useLast = this.useLast();
    const div = this.scale() || 1;
    const labels = pts.map((p) => this.fmtTime(p.ts));
    const values = pts.map((p) => {
      const raw = useLast ? (p.last ?? p.value) : p.value;
      return raw / div;
    });
    const c = this.stroke();
    const datasets: ChartData<ChartType, number[], string>['datasets'] = [
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
  });

  readonly options = computed<ChartConfiguration['options']>(() => {
    const unit = this.unit();
    const overlayUnit = this.overlayUnit();
    const hasOverlay = this.hasOverlay();
    return {
      responsive: true,
      maintainAspectRatio: false,
      animation: false,
      plugins: {
        legend: { display: hasOverlay },
        tooltip: {
          callbacks: {
            label: (ctx) => {
              const u = ctx.datasetIndex === 1 ? overlayUnit : unit;
              return `${ctx.formattedValue}${u ? ' ' + u : ''}`;
            },
          },
        },
      },
      scales: {
        x: {
          ticks: { maxRotation: 0, autoSkip: true, maxTicksLimit: 8 },
          grid: { display: false },
        },
        y: {
          beginAtZero: false,
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
    return d.toLocaleString(undefined, {
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    });
  }

  /** Translucent fill colour for line charts. */
  private alpha(c: string): string {
    if (c.startsWith('#') && c.length === 7) {
      return c + '33';
    }
    return c;
  }
}
