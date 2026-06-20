import { Component, OnInit, inject, signal } from '@angular/core';

import { ApiService } from '../core/api.service';
import { DailyStats } from '../core/models';
import { StatCard } from './stat-card';

// Daily-KPI dashboard widget (L06 / T_DB5): today's derived statistics (self-consumption,
// savings, CO₂, peak PV, round-trip efficiency) as a row of stat cards. A *container* widget —
// it fetches `/api/stats/daily` itself (these KPIs aren't canonical live metrics), wrapping the
// dumb `<app-stat-card>`. Degrades to "—" cards on error/null (missing ≠ zero).
@Component({
  selector: 'app-daily-kpis',
  imports: [StatCard],
  template: `
    <div class="row g-3">
      <div class="col-6 col-md-4 col-lg-2">
        <app-stat-card label="Self-consumption" [value]="pct(stats()?.self_consumption_pct ?? null)" icon="bi-pie-chart" role="success" />
      </div>
      <div class="col-6 col-md-4 col-lg-2">
        <app-stat-card label="Self-sufficiency" [value]="pct(stats()?.self_sufficiency_pct ?? null)" icon="bi-house-check" role="primary" />
      </div>
      <div class="col-6 col-md-4 col-lg-2">
        <app-stat-card label="Savings" [value]="money(stats()?.economics?.savings ?? null, stats()?.currency ?? '')" icon="bi-piggy-bank" role="success" />
      </div>
      <div class="col-6 col-md-4 col-lg-2">
        <app-stat-card label="CO₂ avoided" [value]="kg(stats()?.economics?.co2_avoided_kg ?? null)" unit="kg" icon="bi-leaf" role="success" />
      </div>
      <div class="col-6 col-md-4 col-lg-2">
        <app-stat-card label="Peak PV" [value]="kw(stats()?.peak_pv_w ?? null)" unit="kW" icon="bi-sun" role="warning" />
      </div>
      <div class="col-6 col-md-4 col-lg-2">
        <app-stat-card label="Round-trip eff." [value]="ratioPct(stats()?.round_trip_efficiency ?? null)" icon="bi-arrow-repeat" role="info" />
      </div>
    </div>
  `,
})
export class DailyKpis implements OnInit {
  private readonly api = inject(ApiService);

  /** Today's daily stats for the KPI row (T053). Null until loaded / on error. */
  readonly stats = signal<DailyStats | null>(null);

  ngOnInit(): void {
    this.api.getDailyStats().subscribe({
      next: (s) => this.stats.set(s),
      error: () => this.stats.set(null),
    });
  }

  // --- KPI formatters. Each returns undefined for null ⇒ stat-card shows "—". ---
  pct(v: number | null): string | undefined {
    return v === null ? undefined : `${v.toFixed(0)}%`;
  }
  ratioPct(v: number | null): string | undefined {
    return v === null ? undefined : `${(v * 100).toFixed(0)}%`;
  }
  money(v: number | null, currency: string): string | undefined {
    return v === null ? undefined : `${currency} ${v.toFixed(2)}`;
  }
  kg(v: number | null): string | undefined {
    return v === null ? undefined : v.toFixed(1);
  }
  kw(v: number | null): string | undefined {
    return v === null ? undefined : (v / 1000).toFixed(2);
  }
}
