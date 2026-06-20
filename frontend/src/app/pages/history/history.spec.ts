import { TestBed } from '@angular/core/testing';
import { of } from 'rxjs';

import { HistoryPage } from './history';
import { ApiService } from '../../core/api.service';
import { DashboardConfig } from '../../core/models';

const historyConfig: DashboardConfig = {
  id: 'history',
  name: 'History',
  builtin: true,
  widgets: [
    { type: 'daily-kpis', x: 0, y: 0, w: 12, h: 2, config: {} },
    { type: 'history-chart', x: 0, y: 2, w: 12, h: 6, config: { metric: 'pv_power_w', resolution: '1h', range: 1 } },
  ],
};

// The host instantiates the real child widgets (daily-kpis, history-chart), so stub the API
// calls they make on init too (empty metrics ⇒ no follow-up history fetch).
const fakeApi = {
  getDashboard: () => of(historyConfig),
  putDashboard: () => of(historyConfig),
  deleteDashboard: () => of(undefined),
  getDailyStats: () => of(null),
  getHistoryMetrics: () => of({ device_id: 'd1', metrics: [] }),
} as unknown as ApiService;

describe('HistoryPage', () => {
  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [HistoryPage],
      providers: [{ provide: ApiService, useValue: fakeApi }],
    }).compileComponents();
  });

  it('loads the history built-in and renders the dashboard host', () => {
    const fixture = TestBed.createComponent(HistoryPage);
    fixture.detectChanges();
    expect(fixture.componentInstance.dashboard()?.id).toBe('history');
    expect(fixture.nativeElement.querySelector('app-dashboard-host')).toBeTruthy();
  });

  it('reloads the layout on reset to default', () => {
    const fixture = TestBed.createComponent(HistoryPage);
    fixture.detectChanges();
    fixture.componentInstance.dashboard.set(null);
    fixture.componentInstance.reset();
    expect(fixture.componentInstance.dashboard()?.id).toBe('history');
  });
});
