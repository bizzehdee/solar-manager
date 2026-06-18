import { Component, computed, inject, OnInit, signal } from '@angular/core';
import { DatePipe, DecimalPipe } from '@angular/common';

import { ApiService } from '../../core/api.service';
import { DailyForecast, ForecastResponse, HistoryPoint } from '../../core/models';
import { StatCard } from '../../shared/stat-card';
import { TimeSeriesChart } from '../../shared/time-series-chart';

type ScopeKey = 'today' | 'tomorrow' | '3d' | '7d';

// Forecast view (plan.md §13 / Phase 4): expected PV generation + projected battery SoC,
// scoped to today / tomorrow / 3d / 7d. The full 7-day forecast is fetched once and the
// scope just *filters* it client-side — so switching is instant (no refetch). Read-only;
// the model is configured under Settings › Solar array & site (T064).
@Component({
  selector: 'app-forecast',
  imports: [TimeSeriesChart, StatCard, DatePipe, DecimalPipe],
  template: `
    <div class="d-flex align-items-center justify-content-between mb-3 flex-wrap gap-2">
      <h4 class="mb-0"><i class="bi bi-cloud-sun"></i> Forecast</h4>
      <div class="btn-group btn-group-sm" role="group" aria-label="Forecast range">
        @for (s of scopes; track s.key) {
          <button
            type="button"
            class="btn"
            [class.btn-primary]="scope() === s.key"
            [class.btn-outline-secondary]="scope() !== s.key"
            (click)="scope.set(s.key)"
          >
            {{ s.label }}
          </button>
        }
      </div>
    </div>

    @if (loading()) {
      <div class="text-secondary">
        <span class="spinner-border spinner-border-sm"></span> Loading…
      </div>
    } @else if (forecast(); as f) {
      <!-- KPI row: expected yield for the selected range + projected battery empty/full times. -->
      <div class="row g-3 mb-3">
        <div class="col-12 col-md-4">
          <app-stat-card
            [label]="'Expected ' + scopeLabel().toLowerCase()"
            [value]="expectedKwh()"
            unit="kWh"
            icon="bi-sun"
            role="warning"
          />
        </div>
        <div class="col-6 col-md-4">
          <app-stat-card label="Battery empty at" [value]="depletionLabel()" icon="bi-battery" role="danger" />
        </div>
        <div class="col-6 col-md-4">
          <app-stat-card label="Battery full at" [value]="fullLabel()" icon="bi-battery-full" role="success" />
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
              [yMin]="0"
              [ySuggestedMax]="installedWatts()"
              [overlayPoints]="cloudPoints()"
              overlayLabel="Cloud cover"
              overlayUnit="%"
              overlayColor="#6c757d"
              [overlayMin]="0"
              [overlayMax]="100"
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
              [yMin]="0"
              [yMax]="100"
            />
          </div>
        </div>

        <!-- Per-day report for the selected range (one row per calendar day). -->
        <div class="card">
          <div class="card-header"><i class="bi bi-calendar-week"></i> {{ scopeLabel() }} outlook</div>
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
                @for (d of visibleDaily(); track d.date) {
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

  readonly scopes: { key: ScopeKey; label: string }[] = [
    { key: 'today', label: 'Today' },
    { key: 'tomorrow', label: 'Tomorrow' },
    { key: '3d', label: '3 days' },
    { key: '7d', label: '7 days' },
  ];
  readonly scope = signal<ScopeKey>('today');
  readonly forecast = signal<ForecastResponse | null>(null);
  readonly loading = signal(true);

  /** Total installed DC capacity in watts (Σ array kWp × 1000), the floor for the
   *  generation chart's top value so output always reads against full capacity.
   *  0 ⇒ no floor (chart auto-scales) until the config loads. */
  readonly installedWatts = signal<number | undefined>(undefined);

  readonly scopeLabel = computed(() => this.scopes.find((s) => s.key === this.scope())!.label);

  /** Calendar dates (UTC) in the forecast, ascending; daily[0] is today. */
  private readonly dates = computed(() => (this.forecast()?.daily ?? []).map((d) => d.date));

  /** The set of dates included by the current scope (today / tomorrow / first 3 / all 7). */
  private readonly selectedDates = computed<Set<string>>(() => {
    const d = this.dates();
    switch (this.scope()) {
      case 'today':
        return new Set(d.slice(0, 1));
      case 'tomorrow':
        return new Set(d.slice(1, 2));
      case '3d':
        return new Set(d.slice(0, 3));
      default:
        return new Set(d);
    }
  });

  /** Per-day report rows within the selected scope. */
  readonly visibleDaily = computed<DailyForecast[]>(() =>
    (this.forecast()?.daily ?? []).filter((d) => this.selectedDates().has(d.date)),
  );

  /** Expected PV power curve for the scope, mapped to the chart's {ts,value} shape. */
  readonly generationPoints = computed<HistoryPoint[]>(() =>
    (this.forecast()?.generation ?? [])
      .filter((g) => this.selectedDates().has(utcDate(g.ts)))
      .map((g) => ({ ts: g.ts, value: g.pv_w })),
  );

  /** Cloud-cover (%) curve for the scope, aligned to the generation points by the same
   *  date filter so the chart can overlay it on a second Y axis. */
  readonly cloudPoints = computed<HistoryPoint[]>(() =>
    (this.forecast()?.generation ?? [])
      .filter((g) => this.selectedDates().has(utcDate(g.ts)))
      .map((g) => ({ ts: g.ts, value: g.cloud_cover })),
  );

  /** Projected SoC curve for the scope. */
  readonly socPoints = computed<HistoryPoint[]>(() =>
    (this.forecast()?.soc ?? [])
      .filter((p) => this.selectedDates().has(utcDate(p.ts)))
      .map((p) => ({ ts: p.ts, value: p.soc_pct })),
  );

  /** Total expected generation across the selected range, in kWh (1dp). */
  readonly expectedKwh = computed(() =>
    (this.visibleDaily().reduce((sum, d) => sum + d.expected_wh, 0) / 1000).toFixed(1),
  );

  /** Battery empty/full are whole-projection facts (forward-looking, may be a future day). */
  readonly depletionLabel = computed(() => this.timeLabel(this.forecast()?.depletion_ts ?? null));
  readonly fullLabel = computed(() => this.timeLabel(this.forecast()?.full_ts ?? null));

  ngOnInit(): void {
    // Fetch the full 7-day forecast once; scope switching filters it client-side.
    this.api.getForecast(undefined, 7).subscribe({
      next: (f) => {
        this.forecast.set(f);
        this.loading.set(false);
      },
      error: () => {
        this.forecast.set(null);
        this.loading.set(false);
      },
    });

    // Installed capacity drives the generation chart's axis floor — fetched alongside the
    // forecast; failure just leaves the axis auto-scaled.
    this.api.getForecastConfig().subscribe({
      next: (cfg) => {
        const watts = (cfg.arrays ?? []).reduce((sum, a) => sum + (a.kwp ?? 0) * 1000, 0);
        this.installedWatts.set(watts > 0 ? watts : undefined);
      },
      error: () => this.installedWatts.set(undefined),
    });
  }

  /** Epoch seconds → localised weekday + time (weekday disambiguates a future day),
   *  or "not projected" when the event won't occur within the forecast. */
  private timeLabel(ts: number | null): string {
    if (ts === null) return 'not projected';
    return new Date(ts * 1000).toLocaleString(undefined, {
      weekday: 'short',
      hour: '2-digit',
      minute: '2-digit',
    });
  }
}

/** Epoch seconds → UTC YYYY-MM-DD, matching the backend's per-day grouping. */
function utcDate(ts: number): string {
  return new Date(ts * 1000).toISOString().slice(0, 10);
}
