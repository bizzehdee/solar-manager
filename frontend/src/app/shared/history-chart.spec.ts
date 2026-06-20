import { TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting, HttpTestingController } from '@angular/common/http/testing';
import { provideCharts, withDefaultRegisterables } from 'ng2-charts';

import { HistoryChart } from './history-chart';

describe('HistoryChart', () => {
  let http: HttpTestingController;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [HistoryChart],
      providers: [provideHttpClient(), provideHttpClientTesting(), provideCharts(withDefaultRegisterables())],
    }).compileComponents();
    http = TestBed.inject(HttpTestingController);
  });

  it('loads metrics on init and fetches history for the configured/first metric', () => {
    const fixture = TestBed.createComponent(HistoryChart);
    fixture.detectChanges();

    http.expectOne((r) => r.url === '/api/history/metrics').flush({ device_id: 'd1', metrics: ['pv_power_w', 'today_pv_wh'] });

    const hist = http.expectOne((r) => r.url === '/api/history');
    expect(hist.request.params.get('metric')).toBe('pv_power_w');
    hist.flush({ device_id: 'd1', metric: 'pv_power_w', resolution: '1h', start: 0, end: 0, points: [{ ts: 1_700_000_000, value: 42 }] });
    fixture.detectChanges();

    expect(fixture.componentInstance.points().length).toBe(1);
    expect(fixture.nativeElement.querySelector('app-time-series-chart')).toBeTruthy();
  });

  it('seeds the initial metric from config when present', () => {
    const fixture = TestBed.createComponent(HistoryChart);
    fixture.componentRef.setInput('config', { metric: 'today_pv_wh', resolution: '1d', range: 7 });
    fixture.detectChanges();

    http.expectOne((r) => r.url === '/api/history/metrics').flush({ device_id: 'd1', metrics: ['pv_power_w', 'today_pv_wh'] });
    const hist = http.expectOne((r) => r.url === '/api/history');
    expect(hist.request.params.get('metric')).toBe('today_pv_wh');
    expect(hist.request.params.get('resolution')).toBe('1d');
    hist.flush({ device_id: 'd1', metric: 'today_pv_wh', resolution: '1d', start: 0, end: 0, points: [] });
  });

  it('builds a CSV export href for the current metric + resolution (T091)', () => {
    const fixture = TestBed.createComponent(HistoryChart);
    fixture.detectChanges();
    http.expectOne((r) => r.url === '/api/history/metrics').flush({ device_id: 'd1', metrics: ['pv_power_w'] });
    http.expectOne((r) => r.url === '/api/history').flush({ device_id: 'd1', metric: 'pv_power_w', resolution: '1h', start: 0, end: 0, points: [] });
    fixture.detectChanges();

    const href = fixture.componentInstance.exportHref();
    expect(href).toContain('/api/export?metric=pv_power_w');
    expect(href).toContain('resolution=1h');
    expect(href).toContain('start=');
  });

  it('shows a no-data message when metrics list is empty', () => {
    const fixture = TestBed.createComponent(HistoryChart);
    fixture.detectChanges();
    http.expectOne((r) => r.url === '/api/history/metrics').flush({ device_id: 'd1', metrics: [] });
    fixture.detectChanges();
    expect((fixture.nativeElement as HTMLElement).textContent).toContain('No data yet');
  });

  it('switching metric triggers a new history request', () => {
    const fixture = TestBed.createComponent(HistoryChart);
    fixture.detectChanges();
    http.expectOne((r) => r.url === '/api/history/metrics').flush({ device_id: 'd1', metrics: ['pv_power_w', 'today_pv_wh'] });
    http.expectOne((r) => r.url === '/api/history').flush({ device_id: 'd1', metric: 'pv_power_w', resolution: '1h', start: 0, end: 0, points: [] });

    fixture.componentInstance.onMetric({ target: { value: 'today_pv_wh' } } as unknown as Event);
    const hist = http.expectOne((r) => r.url === '/api/history');
    expect(hist.request.params.get('metric')).toBe('today_pv_wh');
    hist.flush({ device_id: 'd1', metric: 'today_pv_wh', resolution: '1h', start: 0, end: 0, points: [] });
  });
});
