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
  template: `<div style="position:relative;height:320px">
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

  private readonly stroke = computed(() => this.color() ?? '#0d6efd');

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
    return {
      labels,
      datasets: [
        {
          data: values,
          label: this.label(),
          borderColor: c,
          backgroundColor: this.kind() === 'bar' ? c : this.alpha(c),
          pointRadius: 0,
          borderWidth: 2,
          fill: this.kind() === 'line',
          tension: 0.2,
        },
      ],
    };
  });

  readonly options = computed<ChartConfiguration['options']>(() => {
    const unit = this.unit();
    return {
      responsive: true,
      maintainAspectRatio: false,
      animation: false,
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            label: (ctx) => `${ctx.formattedValue}${unit ? ' ' + unit : ''}`,
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
          title: { display: !!unit, text: unit },
        },
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
