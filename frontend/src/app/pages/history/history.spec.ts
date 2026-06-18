import { TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting, HttpTestingController } from '@angular/common/http/testing';
import { provideCharts, withDefaultRegisterables } from 'ng2-charts';

import { HistoryPage } from './history';

describe('HistoryPage', () => {
  let http: HttpTestingController;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [HistoryPage],
      providers: [
        provideHttpClient(),
        provideHttpClientTesting(),
        provideCharts(withDefaultRegisterables()),
      ],
    }).compileComponents();
    http = TestBed.inject(HttpTestingController);
  });

  /** Flush the today's-stats request the page fires on init (T053). */
  function flushStats(over: Record<string, unknown> = {}): void {
    http.expectOne((r) => r.url === '/api/stats/daily').flush({
      device_id: 'd1',
      date: '2026-06-18',
      energy_wh: { pv: 0, load: 0, import: 0, export: 0, charge: 0, discharge: 0 },
      self_consumption_pct: 70,
      self_sufficiency_pct: 88,
      peak_pv_w: 4200,
      round_trip_efficiency: 0.92,
      economics: {
        import_cost: 0,
        export_revenue: 0,
        standing_charge: 0,
        net_cost: 0,
        baseline_cost: 0,
        savings: 1.23,
        co2_avoided_kg: 0.45,
      },
      currency: 'GBP',
      ...over,
    });
  }

  it('renders the KPI row after /api/stats/daily flushes (T053)', () => {
    const fixture = TestBed.createComponent(HistoryPage);
    fixture.detectChanges();

    http.expectOne((r) => r.url === '/api/history/metrics').flush({ device_id: 'd1', metrics: [] });
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
    const fixture = TestBed.createComponent(HistoryPage);
    fixture.detectChanges();
    http.expectOne((r) => r.url === '/api/history/metrics').flush({ device_id: 'd1', metrics: [] });
    flushStats({ self_consumption_pct: null, peak_pv_w: null });
    fixture.detectChanges();
    expect((fixture.nativeElement as HTMLElement).textContent).toContain('—');
  });

  it('loads metrics on init and fetches history for the first metric', () => {
    const fixture = TestBed.createComponent(HistoryPage);
    fixture.detectChanges();

    http.expectOne((r) => r.url === '/api/history/metrics').flush({
      device_id: 'd1',
      metrics: ['pv_power_w', 'today_pv_wh'],
    });
    flushStats();

    const hist = http.expectOne((r) => r.url === '/api/history');
    expect(hist.request.params.get('metric')).toBe('pv_power_w');
    hist.flush({
      device_id: 'd1',
      metric: 'pv_power_w',
      resolution: '1h',
      start: 0,
      end: 0,
      points: [{ ts: 1_700_000_000, value: 42 }],
    });
    fixture.detectChanges();

    expect(fixture.componentInstance.points().length).toBe(1);
    expect(fixture.nativeElement.querySelector('app-time-series-chart')).toBeTruthy();
  });

  it('shows a no-data message when metrics list is empty', () => {
    const fixture = TestBed.createComponent(HistoryPage);
    fixture.detectChanges();
    http.expectOne((r) => r.url === '/api/history/metrics').flush({ device_id: 'd1', metrics: [] });
    flushStats();
    fixture.detectChanges();
    expect((fixture.nativeElement as HTMLElement).textContent).toContain('No data yet');
  });

  it('switching metric triggers a new history request', () => {
    const fixture = TestBed.createComponent(HistoryPage);
    fixture.detectChanges();
    http.expectOne((r) => r.url === '/api/history/metrics').flush({
      device_id: 'd1',
      metrics: ['pv_power_w', 'today_pv_wh'],
    });
    flushStats();
    http.expectOne((r) => r.url === '/api/history').flush({
      device_id: 'd1',
      metric: 'pv_power_w',
      resolution: '1h',
      start: 0,
      end: 0,
      points: [],
    });

    fixture.componentInstance.onMetric({ target: { value: 'today_pv_wh' } } as unknown as Event);
    const req = http.expectOne((r) => r.url === '/api/history');
    expect(req.request.params.get('metric')).toBe('today_pv_wh');
    req.flush({ device_id: 'd1', metric: 'today_pv_wh', resolution: '1h', start: 0, end: 0, points: [] });

    expect(fixture.componentInstance.isCounter()).toBe(true);
    expect(fixture.componentInstance.unit()).toBe('kWh');
  });
});
