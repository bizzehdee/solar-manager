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

  it('fetches history for the first available metric when none is configured', () => {
    const fixture = TestBed.createComponent(HistoryChart);
    fixture.detectChanges(); // constructor fired getHistoryMetrics; effect has no metric yet
    http.expectOne((r) => r.url === '/api/history/metrics').flush({ device_id: 'd1', metrics: ['pv_power_w', 'today_pv_wh'] });
    fixture.detectChanges(); // metric resolves → effect refetches

    const hist = http.expectOne((r) => r.url === '/api/history');
    expect(hist.request.params.get('metric')).toBe('pv_power_w');
    hist.flush({ device_id: 'd1', metric: 'pv_power_w', resolution: '1h', start: 0, end: 0, points: [{ ts: 1, value: 42 }] });
    fixture.detectChanges();

    expect(fixture.componentInstance.points().length).toBe(1);
    expect(fixture.nativeElement.querySelector('app-time-series-chart')).toBeTruthy();
  });

  it('is fully config-driven (metric/resolution/range come from config, no inline controls)', () => {
    const fixture = TestBed.createComponent(HistoryChart);
    fixture.componentRef.setInput('config', { metric: 'today_pv_wh', resolution: '1d', range: 7 });
    fixture.detectChanges();

    http.expectOne((r) => r.url === '/api/history/metrics').flush({ device_id: 'd1', metrics: ['pv_power_w', 'today_pv_wh'] });
    const hist = http.expectOne((r) => r.url === '/api/history');
    expect(hist.request.params.get('metric')).toBe('today_pv_wh');
    expect(hist.request.params.get('resolution')).toBe('1d');
    const span = Math.floor(Date.now() / 1000) - Number(hist.request.params.get('start'));
    expect(span).toBeGreaterThanOrEqual(7 * 86400 - 2);
    hist.flush({ device_id: 'd1', metric: 'today_pv_wh', resolution: '1d', start: 0, end: 0, points: [] });
    fixture.detectChanges();

    // No inline selector controls — configuration is via the dashboard editor's modal.
    const root = fixture.nativeElement as HTMLElement;
    expect(root.querySelector('#hc-metric')).toBeNull();
    expect(root.querySelector('#hc-range')).toBeNull();
  });

  it('refetches when the config (range as a string from the select) changes', () => {
    const fixture = TestBed.createComponent(HistoryChart);
    fixture.componentRef.setInput('config', { metric: 'pv_power_w', resolution: '1h', range: '1' });
    fixture.detectChanges();
    http.expectOne((r) => r.url === '/api/history/metrics').flush({ device_id: 'd1', metrics: ['pv_power_w'] });
    http.expectOne((r) => r.url === '/api/history').flush({ device_id: 'd1', metric: 'pv_power_w', resolution: '1h', start: 0, end: 0, points: [] });

    // Editing the widget config (e.g. range → 30 days) drives a new request.
    fixture.componentRef.setInput('config', { metric: 'pv_power_w', resolution: '1h', range: '30' });
    fixture.detectChanges();
    const hist = http.expectOne((r) => r.url === '/api/history');
    const span = Math.floor(Date.now() / 1000) - Number(hist.request.params.get('start'));
    expect(span).toBeGreaterThanOrEqual(30 * 86400 - 2);
    hist.flush({ device_id: 'd1', metric: 'pv_power_w', resolution: '1h', start: 0, end: 0, points: [] });
  });

  it('shows a no-data message when there is no metric to chart', () => {
    const fixture = TestBed.createComponent(HistoryChart);
    fixture.detectChanges();
    http.expectOne((r) => r.url === '/api/history/metrics').flush({ device_id: 'd1', metrics: [] });
    fixture.detectChanges();
    expect((fixture.nativeElement as HTMLElement).textContent).toContain('No data yet');
  });
});
