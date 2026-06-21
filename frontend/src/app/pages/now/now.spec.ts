import { TestBed } from '@angular/core/testing';
import { signal } from '@angular/core';
import { of } from 'rxjs';

import { NowPage } from './now';
import { ApiService } from '../../core/api.service';
import { LiveService } from '../../core/live.service';
import { DashboardConfig, MetricValue, Snapshot } from '../../core/models';

// Inverter clock now lives in Settings › Diagnostics (per-device health), not on Now.

// Minimal LiveService stub exposing the `snapshot` signal DashboardDataService consumes.
class FakeLiveService {
  readonly snapshot = signal<Snapshot | null>(null);
  set(metrics: Record<string, MetricValue>): void {
    this.snapshot.set({ ts: 't', devices: { d1: { ts: 't', metrics } } });
  }
}

// The "now" built-in layout the page loads via the API (energy-flow + two metric-gauges).
const nowConfig: DashboardConfig = {
  id: 'now',
  name: 'Now',
  builtin: true,
  widgets: [
    { type: 'energy-flow', x: 0, y: 0, w: 6, h: 6, config: {} },
    { type: 'metric-gauge', x: 6, y: 0, w: 2, h: 2, config: { metric: 'pv_power_w', label: 'Solar', unit: 'W', max: 8000 } },
    { type: 'metric-gauge', x: 6, y: 2, w: 2, h: 2, config: { metric: 'battery_soc_pct', label: 'Battery SoC', unit: '%', max: 100 } },
  ],
};

const fakeApi = {
  getDashboard: () => of(nowConfig),
  putDashboard: () => of(nowConfig),
  deleteDashboard: () => of(undefined),
} as unknown as ApiService;

describe('NowPage', () => {
  let live: FakeLiveService;

  beforeEach(async () => {
    live = new FakeLiveService();
    await TestBed.configureTestingModule({
      imports: [NowPage],
      providers: [
        { provide: LiveService, useValue: live },
        { provide: ApiService, useValue: fakeApi },
      ],
    }).compileComponents();
  });

  it('shows the fault banner when inverter_fault_codes is non-empty (T054)', () => {
    const fixture = TestBed.createComponent(NowPage);
    live.set({ battery_soc_pct: 50, inverter_fault_codes: ['F01', 'F23'] });
    fixture.detectChanges();
    const alert = fixture.nativeElement.querySelector('.alert-danger');
    expect(alert).toBeTruthy();
    expect((alert as HTMLElement).textContent).toContain('F01, F23');
  });

  it('hides the fault banner when codes are absent or empty (T054)', () => {
    const fixture = TestBed.createComponent(NowPage);
    live.set({ battery_soc_pct: 50, inverter_fault_codes: [] });
    fixture.detectChanges();
    expect(fixture.nativeElement.querySelector('.alert-danger')).toBeFalsy();
  });

  it('surfaces run_state as a badge (T054)', () => {
    const fixture = TestBed.createComponent(NowPage);
    live.set({ battery_soc_pct: 50, run_state: 'on_grid' });
    fixture.detectChanges();
    const badge = fixture.nativeElement.querySelector('.badge');
    expect((badge as HTMLElement).textContent?.trim()).toBe('on grid');
  });

  it('renders the dashboard host with the now layout (energy-flow + gauges)', () => {
    const fixture = TestBed.createComponent(NowPage);
    live.set({ battery_soc_pct: 60, pv_power_w: 6500 });
    fixture.detectChanges();
    const el = fixture.nativeElement as HTMLElement;
    expect(el.querySelector('app-dashboard-host')).toBeTruthy();
    expect(el.querySelector('app-energy-flow')).toBeTruthy();
    // Two metric-gauges → PowerGauge components; the SoC one renders its '%' unit and value.
    expect(el.querySelectorAll('app-power-gauge svg').length).toBe(2);
    expect(el.textContent).toContain('60 %'); // SoC gauge value + overridden unit
    expect(el.textContent).toContain('6500 W'); // solar gauge — true watts
  });

  it('reloads the layout on reset to default', () => {
    const fixture = TestBed.createComponent(NowPage);
    fixture.detectChanges();
    expect(fixture.componentInstance.dashboard()?.id).toBe('now');
    fixture.componentInstance.dashboard.set(null);
    fixture.componentInstance.reset();
    expect(fixture.componentInstance.dashboard()?.id).toBe('now');
  });
});
