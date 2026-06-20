import { TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting, HttpTestingController } from '@angular/common/http/testing';

import { DailyKpis } from './daily-kpis';

describe('DailyKpis', () => {
  let http: HttpTestingController;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [DailyKpis],
      providers: [provideHttpClient(), provideHttpClientTesting()],
    }).compileComponents();
    http = TestBed.inject(HttpTestingController);
  });

  function flushStats(over: Record<string, unknown> = {}): void {
    http.expectOne((r) => r.url === '/api/stats/daily').flush({
      device_id: 'd1',
      date: '2026-06-18',
      energy_wh: { pv: 0, load: 0, import: 0, export: 0, charge: 0, discharge: 0 },
      self_consumption_pct: 70,
      self_sufficiency_pct: 88,
      peak_pv_w: 4200,
      round_trip_efficiency: 0.92,
      economics: { import_cost: 0, export_revenue: 0, standing_charge: 0, net_cost: 0, baseline_cost: 0, savings: 1.23, co2_avoided_kg: 0.45 },
      currency: 'GBP',
      ...over,
    });
  }

  it('renders the KPI row after /api/stats/daily flushes (T053)', () => {
    const fixture = TestBed.createComponent(DailyKpis);
    fixture.detectChanges();
    flushStats();
    fixture.detectChanges();

    const cards = fixture.nativeElement.querySelectorAll('app-stat-card');
    expect(cards.length).toBe(6);
    const text = (fixture.nativeElement as HTMLElement).textContent ?? '';
    expect(text).toContain('Self-consumption');
    expect(text).toContain('70%');
    expect(text).toContain('GBP 1.23');
    expect(text).toContain('92%'); // round-trip efficiency from 0.92
  });

  it('shows — for null KPI values (T053)', () => {
    const fixture = TestBed.createComponent(DailyKpis);
    fixture.detectChanges();
    flushStats({ self_consumption_pct: null, peak_pv_w: null });
    fixture.detectChanges();
    expect((fixture.nativeElement as HTMLElement).textContent).toContain('—');
  });
});
