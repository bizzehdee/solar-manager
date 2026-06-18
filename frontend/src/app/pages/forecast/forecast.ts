import { Component, computed, inject, OnInit, signal } from '@angular/core';
import { DatePipe, DecimalPipe } from '@angular/common';

import { ApiService } from '../../core/api.service';
import { ForecastResponse, HistoryPoint } from '../../core/models';
import { StatCard } from '../../shared/stat-card';
import { TimeSeriesChart } from '../../shared/time-series-chart';

// Forecast view (plan.md §13 / Phase 4): expected PV generation + projected battery SoC over a
// selectable 1–7 day horizon, a per-day report, plus headline KPIs (expected energy, battery
// empty/full times). Read-only — the model is configured under Settings › Solar array & site (T064).
@Component({
  selector: 'app-forecast',
  imports: [TimeSeriesChart, StatCard, DatePipe, DecimalPipe],
  template: `
    <div class="d-flex align-items-center justify-content-between mb-3 flex-wrap gap-2">
      <h4 class="mb-0"><i class="bi bi-cloud-sun"></i> Forecast</h4>
      <div class="btn-group btn-group-sm" role="group" aria-label="Forecast horizon">
        @for (d of horizons; track d) {
          <button
            type="button"
            class="btn"
            [class.btn-primary]="days() === d"
            [class.btn-outline-secondary]="days() !== d"
            (click)="setDays(d)"
          >
            {{ d }} day{{ d === 1 ? '' : 's' }}
          </button>
        }
      </div>
    </div>

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

        <div class="card mb-3">
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

        <!-- Per-day report: one row per calendar day across the horizon. -->
        <div class="card">
          <div class="card-header"><i class="bi bi-calendar-week"></i> {{ f.days }}-day outlook</div>
          <div class="table-responsive">
            <table class="table table-sm mb-0 align-middle">
              <thead>
                <tr>
                  <th>Day</th>
                  <th class="text-end">Expected PV</th>
                  <th class="text-end">SoC range</th>
                  <th>Battery</th>
                </tr>
              </thead>
              <tbody>
                @for (d of f.daily; track d.date) {
                  <tr>
                    <td>{{ d.date | date: 'EEE d MMM' }}</td>
                    <td class="text-end">{{ d.expected_wh / 1000 | number: '1.1-1' }} kWh</td>
                    <td class="text-end">
                      @if (d.min_soc_pct !== null) {
                        {{ d.min_soc_pct | number: '1.0-0' }}–{{ d.max_soc_pct | number: '1.0-0' }}%
                      } @else {
                        <span class="text-secondary">—</span>
                      }
                    </td>
                    <td>
                      @if (d.battery_depleted) {
                        <span class="badge text-bg-danger"><i class="bi bi-exclamation-triangle"></i> may deplete</span>
                      } @else {
                        <span class="badge text-bg-success">ok</span>
                      }
                    </td>
                  </tr>
                }
              </tbody>
            </table>
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

  readonly horizons = [1, 3, 7];
  readonly days = signal(7);
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
    this.load();
  }

  /** Switch the forecast horizon (1/3/7 days) and reload. */
  setDays(days: number): void {
    if (days === this.days()) return;
    this.days.set(days);
    this.load();
  }

  private load(): void {
    this.loading.set(true);
    this.api.getForecast(undefined, this.days()).subscribe({
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
