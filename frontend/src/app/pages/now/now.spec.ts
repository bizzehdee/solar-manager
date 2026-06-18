import { TestBed } from '@angular/core/testing';
import { signal } from '@angular/core';
import { of } from 'rxjs';

import { NowPage } from './now';
import { ApiService } from '../../core/api.service';
import { LiveService } from '../../core/live.service';
import { MetricValue, Snapshot } from '../../core/models';

// Minimal LiveService stub exposing the `snapshot` signal NowPage consumes.
class FakeLiveService {
  readonly snapshot = signal<Snapshot | null>(null);
  set(metrics: Record<string, MetricValue>): void {
    this.snapshot.set({ ts: 't', devices: { d1: { ts: 't', metrics } } });
  }
}

// ApiService stub: NowPage fetches device ratings + forecast config on init for gauge scales.
const fakeApi = {
  getDevices: () => of({ devices: [{ id: 'd1', ratings: { ac_power_w: 5000 } }] }),
  getForecastConfig: () =>
    of({
      site: { lat: 0, lon: 0, performance_ratio: 0.85 },
      arrays: [{ name: 'A', kwp: 6.5, tilt: 30, azimuth: 180 }],
      battery: { capacity_wh: 16000, min_soc_pct: 10, max_soc_pct: 100, max_charge_w: 4000, max_discharge_w: 4000 },
    }),
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

  it('renders circular gauges for SoC + the four power flows with directions', () => {
    const fixture = TestBed.createComponent(NowPage);
    live.set({
      battery_soc_pct: 60, pv_power_w: 6500, load_power_w: 1200,
      battery_power_w: 3000, grid_power_w: -2000, // battery charging, grid exporting
    });
    fixture.detectChanges();

    const el = fixture.nativeElement as HTMLElement;
    // 5 gauge SVGs: 1 SoC + 4 power.
    expect(el.querySelectorAll('app-soc-gauge svg').length).toBe(1);
    expect(el.querySelectorAll('app-power-gauge svg').length).toBe(4);
    // Directions derived from sign.
    expect(fixture.componentInstance.batteryDir()).toBe('charging');
    expect(fixture.componentInstance.gridDir()).toBe('exporting');
    expect(fixture.componentInstance.batteryAbs()).toBe(3000);
    expect(fixture.componentInstance.gridAbs()).toBe(2000);
    expect(el.textContent).toContain('6.5 kW'); // solar gauge
  });

  it('scales gauges to the actual installation (AC rating, installed PV, battery max)', () => {
    const fixture = TestBed.createComponent(NowPage);
    live.set({ battery_soc_pct: 60 });
    fixture.detectChanges(); // triggers ngOnInit → fetches ratings + forecast config
    const c = fixture.componentInstance;
    expect(c.acRatedW()).toBe(5000); // inverter rated AC (load/grid scale)
    expect(c.solarMax()).toBe(6500); // Σ array kWp × 1000
    expect(c.batteryMax()).toBe(4000); // battery max charge/discharge
  });

  it('hides the battery health panel when neither soh nor cycles present (T055)', () => {
    const fixture = TestBed.createComponent(NowPage);
    live.set({ battery_soc_pct: 50 });
    fixture.detectChanges();
    expect(fixture.componentInstance.hasBatteryHealth()).toBe(false);
    expect((fixture.nativeElement as HTMLElement).textContent).not.toContain('Battery health');
  });
});
