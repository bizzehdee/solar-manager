import { TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting, HttpTestingController } from '@angular/common/http/testing';

import { TimeTrendChart } from './time-trend-chart';
import { HistoryResponse } from '../core/models';

function resp(points: { ts: number; value: number }[]): HistoryResponse {
  return { device_id: 'd1', metric: 'm', resolution: 'raw', start: 0, end: 0, points };
}

describe('TimeTrendChart', () => {
  let http: HttpTestingController;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [TimeTrendChart],
      providers: [provideHttpClient(), provideHttpClientTesting()],
    }).compileComponents();
    http = TestBed.inject(HttpTestingController);
  });

  afterEach(() => http.verify());

  function start(config: Record<string, unknown>): HttpTestingController {
    const fixture = TestBed.createComponent(TimeTrendChart);
    fixture.componentRef.setInput('config', config);
    fixture.detectChanges(); // ngOnInit → load()
    return http;
  }

  it('fetches the configured metric over a "last N minutes" window at raw resolution', () => {
    const now = Math.floor(Date.now() / 1000);
    start({ metric: 'battery_soc_pct', window: 30, window_unit: 'minutes' });
    const req = http.expectOne((r) => r.url === '/api/history');
    expect(req.request.params.get('metric')).toBe('battery_soc_pct');
    expect(req.request.params.get('resolution')).toBe('raw'); // ≤ 3h ⇒ raw
    const startParam = Number(req.request.params.get('start'));
    expect(now - startParam).toBeGreaterThanOrEqual(30 * 60 - 2);
    expect(now - startParam).toBeLessThanOrEqual(30 * 60 + 2);
    req.flush(resp([{ ts: now, value: 55 }]));
  });

  it('uses coarser buckets for multi-day windows', () => {
    start({ metric: 'battery_soc_pct', window: 7, window_unit: 'days' });
    const req = http.expectOne((r) => r.url === '/api/history');
    expect(req.request.params.get('resolution')).toBe('1h'); // > 3 days ⇒ 1h
    const span = Math.floor(Date.now() / 1000) - Number(req.request.params.get('start'));
    expect(span).toBeGreaterThanOrEqual(7 * 86400 - 2);
    req.flush(resp([]));
  });

  it('defaults to last 60 minutes when no window is configured', () => {
    start({ metric: 'pv_power_w' });
    const req = http.expectOne((r) => r.url === '/api/history');
    const span = Math.floor(Date.now() / 1000) - Number(req.request.params.get('start'));
    expect(span).toBeGreaterThanOrEqual(60 * 60 - 2);
    expect(span).toBeLessThanOrEqual(60 * 60 + 2);
    req.flush(resp([]));
  });

  it('does not fetch when no metric is configured', () => {
    start({});
    http.expectNone((r) => r.url === '/api/history');
  });
});
