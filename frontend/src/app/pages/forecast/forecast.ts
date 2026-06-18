import { Component, computed, inject, OnInit, signal } from '@angular/core';

import { ApiService } from '../../core/api.service';
import { ForecastResponse, HistoryPoint } from '../../core/models';
import { StatCard } from '../../shared/stat-card';
import { TimeSeriesChart } from '../../shared/time-series-chart';

// Forecast view (plan.md §13 / Phase 4): expected PV generation + projected battery SoC for
// the rest of the day, plus headline KPIs (expected energy, battery empty/full times). Read-only
// — the model is configured under Settings › Solar array & site (T064).
@Component({
  selector: 'app-forecast',
  imports: [TimeSeriesChart, StatCard],
  template: `
    <h4 class="mb-3"><i class="bi bi-cloud-sun"></i> Forecast</h4>

    @if (loading()) {
      <div class="text-secondary">
        <span class="spinner-border spinner-border-sm"></span> Loading…
      </div>
    } @else if (forecast(); as f) {
      <!-- KPI row: today's expected yield + projected battery empty/full times. -->
      <div class="row g-3 mb-3">
        <div class="col-12 col-md-4">
          <app-stat-card
            label="Expected today"
            [value]="kwh(f.expected_today_wh)"
            unit="kWh"
            icon="bi-sun"
            role="warning"
          />
        </div>
        <div class="col-6 col-md-4">
          <app-stat-card
            label="Battery empty at"
            [value]="depletionLabel()"
            icon="bi-battery"
            role="danger"
          />
        </div>
        <div class="col-6 col-md-4">
          <app-stat-card
            label="Battery full at"
            [value]="fullLabel()"
            icon="bi-battery-full"
            role="success"
          />
        </div>
      </div>

      @if (f.generation.length === 0) {
        <div class="alert alert-secondary">
          No forecast available yet — set your location and array under Settings.
        </div>
      } @else {
        <div class="card mb-3">
          <div class="card-header"><i class="bi bi-sun"></i> Expected generation</div>
          <div class="card-body">
            <app-time-series-chart
              [points]="generationPoints()"
              label="Expected PV"
              unit="W"
              kind="line"
            />
          </div>
        </div>

        <div class="card">
          <div class="card-header"><i class="bi bi-battery-charging"></i> Projected battery SoC</div>
          <div class="card-body">
            <app-time-series-chart
              [points]="socPoints()"
              label="Projected SoC"
              unit="%"
              kind="line"
              color="#198754"
            />
          </div>
        </div>
      }
    } @else {
      <div class="alert alert-secondary">
        No forecast available — set your location and array under Settings.
      </div>
    }
  `,
})
export class ForecastPage implements OnInit {
  private readonly api = inject(ApiService);

  readonly forecast = signal<ForecastResponse | null>(null);
  readonly loading = signal(true);

  /** Expected PV power curve, mapped to the chart's {ts,value} point shape. */
  readonly generationPoints = computed<HistoryPoint[]>(() =>
    (this.forecast()?.generation ?? []).map((g) => ({ ts: g.ts, value: g.pv_w })),
  );

  /** Projected battery SoC curve, mapped to the chart's {ts,value} point shape. */
  readonly socPoints = computed<HistoryPoint[]>(() =>
    (this.forecast()?.soc ?? []).map((p) => ({ ts: p.ts, value: p.soc_pct })),
  );

  /** "Battery empty at" — a local time, or a sentinel when no depletion is projected. */
  readonly depletionLabel = computed(() => this.timeLabel(this.forecast()?.depletion_ts ?? null));
  /** "Battery full at" — a local time, or a sentinel when no full charge is projected. */
  readonly fullLabel = computed(() => this.timeLabel(this.forecast()?.full_ts ?? null));

  ngOnInit(): void {
    this.api.getForecast().subscribe({
      next: (f) => {
        this.forecast.set(f);
        this.loading.set(false);
      },
      error: () => {
        this.forecast.set(null);
        this.loading.set(false);
      },
    });
  }

  /** Wh → kWh to 1dp for the headline KPI. */
  kwh(wh: number): string {
    return (wh / 1000).toFixed(1);
  }

  /** Epoch seconds → localised hh:mm, or "not projected" when the event won't occur. */
  private timeLabel(ts: number | null): string {
    if (ts === null) return 'not projected';
    return new Date(ts * 1000).toLocaleTimeString(undefined, {
      hour: '2-digit',
      minute: '2-digit',
    });
  }
}
