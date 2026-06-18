import { TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting, HttpTestingController } from '@angular/common/http/testing';
import { provideCharts, withDefaultRegisterables } from 'ng2-charts';

import { ForecastPage } from './forecast';
import { ForecastResponse } from '../../core/models';

function forecast(over: Partial<ForecastResponse> = {}): ForecastResponse {
  return {
    device_id: 'd1',
    generation: [
      { ts: 1_700_000_000, pv_w: 4200, ghi: 800, temp_c: 22 },
      { ts: 1_700_003_600, pv_w: 3800, ghi: 700, temp_c: 23 },
    ],
    soc: [
      { ts: 1_700_000_000, soc_pct: 65, pv_w: 4200, load_w: 600, battery_w: 3600, grid_w: 0 },
      { ts: 1_700_003_600, soc_pct: 80, pv_w: 3800, load_w: 600, battery_w: 3200, grid_w: 0 },
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
});
