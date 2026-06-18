import { TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting, HttpTestingController } from '@angular/common/http/testing';
import { provideCharts, withDefaultRegisterables } from 'ng2-charts';

import { ForecastPage } from './forecast';
import { ForecastResponse } from '../../core/models';

function forecast(over: Partial<ForecastResponse> = {}): ForecastResponse {
  return {
    device_id: 'd1',
    days: 7,
    generation: [
      { ts: 1_700_000_000, pv_w: 4200, ghi: 800, temp_c: 22 },
      { ts: 1_700_003_600, pv_w: 3800, ghi: 700, temp_c: 23 },
    ],
    soc: [
      { ts: 1_700_000_000, soc_pct: 65, pv_w: 4200, load_w: 600, battery_w: 3600, grid_w: 0 },
      { ts: 1_700_003_600, soc_pct: 80, pv_w: 3800, load_w: 600, battery_w: 3200, grid_w: 0 },
    ],
    daily: [
      { date: '2023-11-14', expected_wh: 12000, min_soc_pct: 30, max_soc_pct: 90, battery_depleted: false },
      { date: '2023-11-15', expected_wh: 8000, min_soc_pct: 9, max_soc_pct: 70, battery_depleted: true },
    ],
    depletion_ts: null,
    full_ts: 1_700_010_000,
    expected_today_wh: 12000,
    currency: 'GBP',
    ...over,
  };
}

describe('ForecastPage', () => {
  let http: HttpTestingController;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [ForecastPage],
      providers: [
        provideHttpClient(),
        provideHttpClientTesting(),
        provideCharts(withDefaultRegisterables()),
      ],
    }).compileComponents();
    http = TestBed.inject(HttpTestingController);
  });

  it('fetches /api/forecast on init', () => {
    const fixture = TestBed.createComponent(ForecastPage);
    fixture.detectChanges();
    const req = http.expectOne((r) => r.url === '/api/forecast');
    expect(req.request.method).toBe('GET');
    req.flush(forecast());
  });

  it('renders the KPI cards and charts after the forecast flushes', () => {
    const fixture = TestBed.createComponent(ForecastPage);
    fixture.detectChanges();
    http.expectOne((r) => r.url === '/api/forecast').flush(forecast());
    fixture.detectChanges();

    const el = fixture.nativeElement as HTMLElement;
    expect(el.querySelectorAll('app-stat-card').length).toBe(3);
    expect(el.querySelectorAll('app-time-series-chart').length).toBe(2);

    const text = el.textContent ?? '';
    expect(text).toContain('Expected today');
    expect(text).toContain('12.0'); // 12000 Wh → 12.0 kWh
    expect(text).toContain('Battery empty at');
    expect(text).toContain('not projected'); // depletion_ts is null
  });

  it('shows the empty state when generation is empty', () => {
    const fixture = TestBed.createComponent(ForecastPage);
    fixture.detectChanges();
    http.expectOne((r) => r.url === '/api/forecast').flush(forecast({ generation: [] }));
    fixture.detectChanges();

    const el = fixture.nativeElement as HTMLElement;
    expect(el.textContent).toContain('No forecast available');
    expect(el.querySelectorAll('app-time-series-chart').length).toBe(0);
  });

  it('requests a 7-day horizon by default and renders the per-day report', () => {
    const fixture = TestBed.createComponent(ForecastPage);
    fixture.detectChanges();
    const req = http.expectOne((r) => r.url === '/api/forecast');
    expect(req.request.params.get('days')).toBe('7');
    req.flush(forecast());
    fixture.detectChanges();

    const el = fixture.nativeElement as HTMLElement;
    expect(el.textContent).toContain('7-day outlook');
    expect(el.querySelectorAll('tbody tr').length).toBe(2); // two daily rows
    expect(el.textContent).toContain('may deplete'); // day 2 flagged
  });

  it('re-fetches with the selected horizon when a preset is clicked', () => {
    const fixture = TestBed.createComponent(ForecastPage);
    fixture.detectChanges();
    http.expectOne((r) => r.url === '/api/forecast').flush(forecast());
    fixture.detectChanges();

    // Click the "3 days" preset (first horizon button matching text).
    const buttons = Array.from(
      (fixture.nativeElement as HTMLElement).querySelectorAll('.btn-group button'),
    ) as HTMLButtonElement[];
    buttons.find((b) => b.textContent?.includes('3 day'))!.click();
    fixture.detectChanges();

    const req = http.expectOne((r) => r.url === '/api/forecast');
    expect(req.request.params.get('days')).toBe('3');
    req.flush(forecast({ days: 3 }));
  });
});
