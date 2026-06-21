import { TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting, HttpTestingController } from '@angular/common/http/testing';
import { provideCharts, withDefaultRegisterables } from 'ng2-charts';

import { ChartWidget } from './chart-widget';

describe('ChartWidget', () => {
  let http: HttpTestingController;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [ChartWidget],
      providers: [provideHttpClient(), provideHttpClientTesting(), provideCharts(withDefaultRegisterables())],
    }).compileComponents();
    http = TestBed.inject(HttpTestingController);
  });

  function create(config?: Record<string, unknown>) {
    const fixture = TestBed.createComponent(ChartWidget);
    if (config) fixture.componentRef.setInput('config', config);
    fixture.detectChanges();
    return fixture;
  }

  it('fetches the configured metric over a "last N minutes" window at raw resolution', () => {
    const now = Math.floor(Date.now() / 1000);
    const fixture = create({ metric: 'battery_soc_pct', window: 30, window_unit: 'minutes' });
    http.expectOne((r) => r.url === '/api/history/metrics').flush({ device_id: 'd1', metrics: ['battery_soc_pct'] });

    const req = http.expectOne((r) => r.url === '/api/history');
    expect(req.request.params.get('metric')).toBe('battery_soc_pct');
    expect(req.request.params.get('resolution')).toBe('raw'); // ≤ 3h ⇒ raw
    const span = now - Number(req.request.params.get('start'));
    expect(span).toBeGreaterThanOrEqual(30 * 60 - 2);
    expect(span).toBeLessThanOrEqual(30 * 60 + 2);
    req.flush({ device_id: 'd1', metric: 'battery_soc_pct', resolution: 'raw', start: 0, end: 0, points: [{ ts: now, value: 55 }] });
    fixture.detectChanges();
    expect(fixture.componentInstance.seriesData().length).toBe(1);
    expect(fixture.componentInstance.seriesData()[0].points.length).toBe(1);
    expect(fixture.nativeElement.querySelector('app-time-series-chart')).toBeTruthy();
  });

  it('charts multiple metrics — one /api/history request per series, each a series with a colour', () => {
    const now = Math.floor(Date.now() / 1000);
    const fixture = create({
      metrics: [
        { metric: 'pv_power_w', label: 'Solar', color: '#198754' },
        { metric: 'load_power_w' }, // colour auto-assigned
      ],
      window: 1, window_unit: 'hours', stacked: true,
    });
    http.expectOne((r) => r.url === '/api/history/metrics').flush({ device_id: 'd1', metrics: ['pv_power_w'] });

    const reqs = http.match((r) => r.url === '/api/history');
    expect(reqs.length).toBe(2);
    expect(reqs.map((r) => r.request.params.get('metric')).sort()).toEqual(['load_power_w', 'pv_power_w']);
    reqs[0].flush({ device_id: 'd1', metric: 'pv_power_w', resolution: 'raw', start: 0, end: 0, points: [{ ts: now, value: 1000 }] });
    reqs[1].flush({ device_id: 'd1', metric: 'load_power_w', resolution: 'raw', start: 0, end: 0, points: [{ ts: now, value: 800 }] });
    fixture.detectChanges();

    const series = fixture.componentInstance.seriesData();
    expect(series.length).toBe(2);
    expect(series[0]).toMatchObject({ label: 'Solar', color: '#198754' });
    expect(series[1].label).toBe('Load power'); // humanised fallback
    expect(fixture.componentInstance.stacked()).toBe(true);
    expect(fixture.componentInstance.heading()).toBe('2 metrics');
  });

  it('auto-derives a coarser bucket for multi-day windows', () => {
    create({ metric: 'battery_soc_pct', window: 7, window_unit: 'days' });
    http.expectOne((r) => r.url === '/api/history/metrics').flush({ device_id: 'd1', metrics: ['battery_soc_pct'] });
    const req = http.expectOne((r) => r.url === '/api/history');
    expect(req.request.params.get('resolution')).toBe('1h'); // > 3 days ⇒ 1h
    req.flush({ device_id: 'd1', metric: 'battery_soc_pct', resolution: '1h', start: 0, end: 0, points: [] });
  });

  it('honours a pinned resolution over the auto heuristic', () => {
    create({ metric: 'pv_power_w', window: 30, window_unit: 'minutes', resolution: '1h' });
    http.expectOne((r) => r.url === '/api/history/metrics').flush({ device_id: 'd1', metrics: ['pv_power_w'] });
    const req = http.expectOne((r) => r.url === '/api/history');
    expect(req.request.params.get('resolution')).toBe('1h');
    req.flush({ device_id: 'd1', metric: 'pv_power_w', resolution: '1h', start: 0, end: 0, points: [] });
  });

  it('reads the legacy history-chart shape ({ resolution, range } in days)', () => {
    create({ metric: 'today_pv_wh', resolution: '1d', range: 7 });
    http.expectOne((r) => r.url === '/api/history/metrics').flush({ device_id: 'd1', metrics: ['today_pv_wh'] });
    const req = http.expectOne((r) => r.url === '/api/history');
    expect(req.request.params.get('resolution')).toBe('1d');
    const span = Math.floor(Date.now() / 1000) - Number(req.request.params.get('start'));
    expect(span).toBeGreaterThanOrEqual(7 * 86400 - 2);
    req.flush({ device_id: 'd1', metric: 'today_pv_wh', resolution: '1d', start: 0, end: 0, points: [] });
    expect(span).toBeLessThanOrEqual(7 * 86400 + 2);
  });

  it('falls back to the first available metric when none is configured', () => {
    const fixture = create();
    http.expectOne((r) => r.url === '/api/history/metrics').flush({ device_id: 'd1', metrics: ['pv_power_w', 'today_pv_wh'] });
    fixture.detectChanges(); // metric resolves → effect refetches
    const req = http.expectOne((r) => r.url === '/api/history');
    expect(req.request.params.get('metric')).toBe('pv_power_w');
    req.flush({ device_id: 'd1', metric: 'pv_power_w', resolution: '1h', start: 0, end: 0, points: [] });
  });

  it('refetches when the config changes (range as a string from the select)', () => {
    const fixture = create({ metric: 'pv_power_w', resolution: '1h', range: '1' });
    http.expectOne((r) => r.url === '/api/history/metrics').flush({ device_id: 'd1', metrics: ['pv_power_w'] });
    http.expectOne((r) => r.url === '/api/history').flush({ device_id: 'd1', metric: 'pv_power_w', resolution: '1h', start: 0, end: 0, points: [] });

    fixture.componentRef.setInput('config', { metric: 'pv_power_w', resolution: '1h', range: '30' });
    fixture.detectChanges();
    const req = http.expectOne((r) => r.url === '/api/history');
    const span = Math.floor(Date.now() / 1000) - Number(req.request.params.get('start'));
    expect(span).toBeGreaterThanOrEqual(30 * 86400 - 2);
    req.flush({ device_id: 'd1', metric: 'pv_power_w', resolution: '1h', start: 0, end: 0, points: [] });
  });

  it('shows a configurable header (falls back to the humanised metric)', () => {
    const fixture = create({ metric: 'pv_power_w', label: 'Solar output', window: 1, window_unit: 'days' });
    http.expectOne((r) => r.url === '/api/history/metrics').flush({ device_id: 'd1', metrics: ['pv_power_w'] });
    http.expectOne((r) => r.url === '/api/history').flush({ device_id: 'd1', metric: 'pv_power_w', resolution: '5m', start: 0, end: 0, points: [] });
    fixture.detectChanges();
    expect((fixture.nativeElement as HTMLElement).textContent).toContain('Solar output');
    expect(fixture.componentInstance.heading()).toBe('Solar output');
  });

  it('shows a no-data message when there is no metric to chart', () => {
    const fixture = create();
    http.expectOne((r) => r.url === '/api/history/metrics').flush({ device_id: 'd1', metrics: [] });
    fixture.detectChanges();
    expect((fixture.nativeElement as HTMLElement).textContent).toContain('No data yet');
  });
});
