import { TestBed } from '@angular/core/testing';
import { signal } from '@angular/core';
import { of } from 'rxjs';

import { NowPage } from './now';
import { ApiService } from '../../core/api.service';
import { LiveService } from '../../core/live.service';
import { DashboardConfig, MetricValue, Snapshot } from '../../core/models';

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

let clockResponse = {
  device_id: 'd1', supported: true, device_time: '2026-06-21T12:01:35',
  system_time: '2026-06-21T12:00:00', drift_s: 95, syncable: true,
};
const syncCalls: string[] = [];

const fakeApi = {
  getDashboard: () => of(nowConfig),
  putDashboard: () => of(nowConfig),
  deleteDashboard: () => of(undefined),
  getDevices: () => of({ devices: [{ id: 'd1', ratings: { ac_power_w: 5000 } }] }),
  getDeviceClock: () => of(clockResponse),
  syncDeviceClock: (id: string) => {
    syncCalls.push(id);
    clockResponse = { ...clockResponse, drift_s: 0 };
    return of({ ok: true, drift_s: 0 });
  },
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

  it('renders the battery health panel when battery_soh_pct is present (T055)', () => {
    const fixture = TestBed.createComponent(NowPage);
    live.set({ battery_soc_pct: 50, battery_soh_pct: 98, battery_cycles: 120, battery_temp_c: 25 });
    fixture.detectChanges();
    expect(fixture.componentInstance.hasBatteryHealth()).toBe(true);
    const text = (fixture.nativeElement as HTMLElement).textContent ?? '';
    expect(text).toContain('Battery health');
    expect(text).toContain('98 %');
    expect(text).toContain('120');
  });

  it('hides the battery health panel when neither soh nor cycles present (T055)', () => {
    const fixture = TestBed.createComponent(NowPage);
    live.set({ battery_soc_pct: 50 });
    fixture.detectChanges();
    expect(fixture.componentInstance.hasBatteryHealth()).toBe(false);
    expect((fixture.nativeElement as HTMLElement).textContent).not.toContain('Battery health');
  });

  it('shows inverter clock drift and syncs to system time', () => {
    clockResponse = {
      device_id: 'd1', supported: true, device_time: '2026-06-21T12:01:35',
      system_time: '2026-06-21T12:00:00', drift_s: 95, syncable: true,
    };
    syncCalls.length = 0;
    const fixture = TestBed.createComponent(NowPage);
    live.set({ battery_soc_pct: 60 });
    fixture.detectChanges(); // ngOnInit → getDevices → getDeviceClock

    const el = fixture.nativeElement as HTMLElement;
    expect(el.textContent).toContain('Inverter clock');
    expect(el.textContent).toContain('+95 s'); // seconds shown under 2 min
    expect(fixture.componentInstance.driftLabel(clockResponse)).toBe('+95 s');

    fixture.componentInstance.syncClock();
    expect(syncCalls).toEqual(['d1']);
    expect(fixture.componentInstance.clock()?.drift_s).toBe(0);
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
