import { TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting, HttpTestingController } from '@angular/common/http/testing';

import { SettingsPage } from './settings';
import { DeviceConfig, ForecastConfig, StatsConfig } from '../../core/models';

function statsConfig(over: Partial<StatsConfig> = {}): StatsConfig {
  return {
    tariff: {
      currency: 'GBP',
      import_rate: { flat: 0.3, windows: [] },
      export_rate: { flat: 0.15, windows: [] },
      seasons: [],
    },
    economics: { co2_intensity_g_per_kwh: 200, system_cost: 5000 },
    ...over,
  };
}

function forecastConfig(over: Partial<ForecastConfig> = {}): ForecastConfig {
  return {
    site: { lat: 51.5, lon: -0.12, performance_ratio: 0.85 },
    arrays: [{ name: 'Roof', kwp: 5, tilt: 30, azimuth: 180 }],
    battery: { capacity_wh: 10000, min_soc_pct: 10, max_soc_pct: 100 },
    ...over,
  };
}

function device(over: Partial<DeviceConfig> = {}): DeviceConfig {
  return {
    id: 'd1',
    name: 'Inverter',
    vendor: 'dummy',
    profile: 'dummy',
    transport: 'dummy',
    params: {},
    poll_interval: null,
    bms_topology: 'single',
    enabled: true,
    online: true,
    last_sample_age_s: 1,
    capabilities: ['read', 'control'],
    control: false,
    ...over,
  };
}

describe('SettingsPage', () => {
  let http: HttpTestingController;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [SettingsPage],
      providers: [provideHttpClient(), provideHttpClientTesting()],
    }).compileComponents();
    http = TestBed.inject(HttpTestingController);
  });

  /** Flush the tariff + forecast config the page loads on init. */
  function flushConfig(over: Partial<StatsConfig> = {}): void {
    http.expectOne('/api/stats/config').flush(statsConfig(over));
    http.expectOne('/api/forecast/config').flush(forecastConfig());
  }

  it('renders the device list from /api/devices', () => {
    const fixture = TestBed.createComponent(SettingsPage);
    fixture.detectChanges();
    http.expectOne('/api/devices').flush({ devices: [device({ name: 'My Inverter' })] });
    flushConfig();
    fixture.detectChanges();
    expect((fixture.nativeElement as HTMLElement).textContent).toContain('My Inverter');
  });

  it('submitting the add form POSTs to /api/devices and refreshes', () => {
    const fixture = TestBed.createComponent(SettingsPage);
    fixture.detectChanges();
    http.expectOne('/api/devices').flush({ devices: [] });
    flushConfig();

    fixture.componentInstance.form.id = 'd2';
    fixture.componentInstance.form.transport = 'dummy';
    fixture.componentInstance.add();

    const post = http.expectOne((r) => r.method === 'POST' && r.url === '/api/devices');
    expect(post.request.body).toMatchObject({ id: 'd2', transport: 'dummy' });
    post.flush(device({ id: 'd2' }));

    // refresh after create
    http.expectOne((r) => r.method === 'GET' && r.url === '/api/devices').flush({ devices: [device({ id: 'd2' })] });
    fixture.detectChanges();
    expect(fixture.componentInstance.devices().length).toBe(1);
  });

  it('shows an inline error on 409', () => {
    const fixture = TestBed.createComponent(SettingsPage);
    fixture.detectChanges();
    http.expectOne('/api/devices').flush({ devices: [] });
    flushConfig();

    fixture.componentInstance.form.id = 'dup';
    fixture.componentInstance.add();
    http
      .expectOne((r) => r.method === 'POST')
      .flush({}, { status: 409, statusText: 'Conflict' });
    fixture.detectChanges();
    expect(fixture.componentInstance.error()).toContain('already exists');
  });

  it('loads the tariff form from /api/stats/config (T051)', () => {
    const fixture = TestBed.createComponent(SettingsPage);
    fixture.detectChanges();
    http.expectOne('/api/devices').flush({ devices: [] });
    flushConfig();
    fixture.detectChanges();
    expect(fixture.componentInstance.tariff.currency).toBe('GBP');
    expect(fixture.componentInstance.tariff.importRate).toBe(0.3);
    expect(fixture.componentInstance.tariff.exportRate).toBe(0.15);
    expect(fixture.componentInstance.tariff.co2Intensity).toBe(200);
  });

  it('saveTariff() PUTs flat rates + economics to /api/stats/config (T052)', () => {
    const fixture = TestBed.createComponent(SettingsPage);
    fixture.detectChanges();
    http.expectOne('/api/devices').flush({ devices: [] });
    flushConfig();

    fixture.componentInstance.tariff = {
      currency: 'EUR',
      importRate: 0.4,
      exportRate: 0.2,
      co2Intensity: 150,
      systemCost: 6000,
    };
    fixture.componentInstance.saveTariff();

    const put = http.expectOne((r) => r.method === 'PUT' && r.url === '/api/stats/config');
    expect(put.request.body).toEqual({
      tariff: { import_rate: 0.4, export_rate: 0.2, currency: 'EUR' },
      economics: { co2_intensity_g_per_kwh: 150, system_cost: 6000 },
    });
    put.flush(statsConfig({ tariff: { currency: 'EUR', import_rate: { flat: 0.4, windows: [] }, export_rate: { flat: 0.2, windows: [] }, seasons: [] } }));
    fixture.detectChanges();
    expect(fixture.componentInstance.tariffSaved()).toBe(true);
  });

  it('loads the forecast config from /api/forecast/config (T064)', () => {
    const fixture = TestBed.createComponent(SettingsPage);
    fixture.detectChanges();
    http.expectOne('/api/devices').flush({ devices: [] });
    flushConfig();
    fixture.detectChanges();
    expect(fixture.componentInstance.forecast.site.lat).toBe(51.5);
    expect(fixture.componentInstance.forecast.arrays.length).toBe(1);
    expect(fixture.componentInstance.forecast.battery.capacity_wh).toBe(10000);
  });

  it('addSegment()/removeSegment() change the array length (T064)', () => {
    const fixture = TestBed.createComponent(SettingsPage);
    fixture.detectChanges();
    http.expectOne('/api/devices').flush({ devices: [] });
    flushConfig();

    expect(fixture.componentInstance.forecast.arrays.length).toBe(1);
    fixture.componentInstance.addSegment();
    expect(fixture.componentInstance.forecast.arrays.length).toBe(2);
    fixture.componentInstance.removeSegment(0);
    expect(fixture.componentInstance.forecast.arrays.length).toBe(1);
  });

  it('saveForecast() PUTs site/arrays/battery to /api/forecast/config (T064)', () => {
    const fixture = TestBed.createComponent(SettingsPage);
    fixture.detectChanges();
    http.expectOne('/api/devices').flush({ devices: [] });
    flushConfig();

    fixture.componentInstance.saveForecast();
    const put = http.expectOne((r) => r.method === 'PUT' && r.url === '/api/forecast/config');
    expect(put.request.body).toEqual({
      site: { lat: 51.5, lon: -0.12, performance_ratio: 0.85 },
      arrays: [{ name: 'Roof', kwp: 5, tilt: 30, azimuth: 180 }],
      battery: { capacity_wh: 10000, min_soc_pct: 10, max_soc_pct: 100 },
    });
    put.flush(forecastConfig());
    fixture.detectChanges();
    expect(fixture.componentInstance.forecastSaved()).toBe(true);
  });
});
