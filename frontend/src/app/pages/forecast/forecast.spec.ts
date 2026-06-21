import { TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting, HttpTestingController } from '@angular/common/http/testing';
import { provideCharts, withDefaultRegisterables } from 'ng2-charts';

import { ForecastPage } from './forecast';
import { ForecastConfig, ForecastResponse } from '../../core/models';

function config(over: Partial<ForecastConfig> = {}): ForecastConfig {
  return {
    site: { lat: 51.5, lon: -0.13, performance_ratio: 0.8 },
    arrays: [
      { name: 'A', kwp: 3.5, tilt: 35, azimuth: 135 },
      { name: 'B', kwp: 3.0, tilt: 35, azimuth: 225 },
    ],
    battery: { capacity_wh: 16000, min_soc_pct: 10, max_soc_pct: 100 },
    ...over,
  };
}

function forecast(over: Partial<ForecastResponse> = {}): ForecastResponse {
  return {
    device_id: 'd1',
    days: 7,
    generation: [
      { ts: 1_700_000_000, pv_w: 4200, ghi: 800, cloud_cover: 20, temp_c: 22 },
      { ts: 1_700_003_600, pv_w: 3800, ghi: 700, cloud_cover: 45, temp_c: 23 },
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

  afterEach(() => http.verify());

  /** Flush the config request the page fires on init (alongside the forecast). */
  function flushConfig(over: Partial<ForecastConfig> = {}): void {
    http.expectOne((r) => r.url === '/api/forecast/config').flush(config(over));
  }

  it('fetches /api/forecast on init', () => {
    const fixture = TestBed.createComponent(ForecastPage);
    fixture.detectChanges();
    const req = http.expectOne((r) => r.url === '/api/forecast');
    expect(req.request.method).toBe('GET');
    req.flush(forecast());
    flushConfig();
  });

  it('derives the installed-capacity axis floor from the forecast config', () => {
    const fixture = TestBed.createComponent(ForecastPage);
    fixture.detectChanges();
    http.expectOne((r) => r.url === '/api/forecast').flush(forecast());
    flushConfig(); // 3.5 + 3.0 kWp → 6500 W
    expect(fixture.componentInstance.installedWatts()).toBe(6500);
  });

  it('renders the KPI cards and charts after the forecast flushes', () => {
    const fixture = TestBed.createComponent(ForecastPage);
    fixture.detectChanges();
    http.expectOne((r) => r.url === '/api/forecast').flush(forecast());
    flushConfig();
    fixture.detectChanges();

    const el = fixture.nativeElement as HTMLElement;
    expect(el.querySelectorAll('app-metric-card').length).toBe(3);
    expect(el.querySelectorAll('app-time-series-chart').length).toBe(2);

    const text = el.textContent ?? '';
    expect(text).toContain('Expected today');
    expect(text).toContain('12.0'); // 12000 Wh → 12.0 kWh
    expect(text).toContain('Battery empty at');
    expect(text).toContain('not projected'); // depletion_ts is null
  });

  it('exposes a cloud-cover overlay aligned to the generation curve', () => {
    const fixture = TestBed.createComponent(ForecastPage);
    fixture.detectChanges();
    http.expectOne((r) => r.url === '/api/forecast').flush(forecast());
    flushConfig();
    fixture.detectChanges();

    // 'today' scope keeps the first calendar day (both points share 2023-11-14 UTC).
    const cloud = fixture.componentInstance.cloudPoints();
    expect(cloud.map((p) => p.value)).toEqual([20, 45]);
  });

  it('shows the empty state when generation is empty', () => {
    const fixture = TestBed.createComponent(ForecastPage);
    fixture.detectChanges();
    http.expectOne((r) => r.url === '/api/forecast').flush(forecast({ generation: [] }));
    flushConfig();
    fixture.detectChanges();

    const el = fixture.nativeElement as HTMLElement;
    expect(el.textContent).toContain('No forecast available');
    expect(el.querySelectorAll('app-time-series-chart').length).toBe(0);
  });

  it('fetches the full 7-day forecast once and defaults to the Today scope', () => {
    const fixture = TestBed.createComponent(ForecastPage);
    fixture.detectChanges();
    const req = http.expectOne((r) => r.url === '/api/forecast');
    expect(req.request.params.get('days')).toBe('7'); // always fetch the full week
    req.flush(forecast());
    flushConfig();
    fixture.detectChanges();

    const el = fixture.nativeElement as HTMLElement;
    expect(el.textContent).toContain('Today outlook');
    // Today only → just the first daily row (2023-11-14, not depleted).
    expect(el.querySelectorAll('tbody tr').length).toBe(1);
    expect(el.textContent).not.toContain('may deplete');
    expect(el.textContent).toContain('Expected today');
  });

  function clickScope(fixture: ReturnType<typeof TestBed.createComponent>, label: string): void {
    const buttons = Array.from(
      (fixture.nativeElement as HTMLElement).querySelectorAll('.btn-group button'),
    ) as HTMLButtonElement[];
    buttons.find((b) => b.textContent?.trim() === label)!.click();
    fixture.detectChanges();
  }

  it('switches scope client-side without re-fetching', () => {
    const fixture = TestBed.createComponent(ForecastPage);
    fixture.detectChanges();
    http.expectOne((r) => r.url === '/api/forecast').flush(forecast());
    flushConfig();
    fixture.detectChanges();

    // 7 days → both daily rows, including the depleted day 2. No new HTTP request
    // (afterEach http.verify() would fail if a fetch fired).
    clickScope(fixture, '7 days');
    const el = fixture.nativeElement as HTMLElement;
    expect(el.querySelectorAll('tbody tr').length).toBe(2);
    expect(el.textContent).toContain('may deplete');

    // Tomorrow → just day 2 (the depleted one).
    clickScope(fixture, 'Tomorrow');
    expect(el.querySelectorAll('tbody tr').length).toBe(1);
    expect(el.textContent).toContain('may deplete');
    expect(el.textContent).toContain('Expected tomorrow');
  });
});
