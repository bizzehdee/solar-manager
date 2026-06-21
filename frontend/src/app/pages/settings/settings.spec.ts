import { TestBed } from '@angular/core/testing';
import { provideRouter, Router } from '@angular/router';
import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting, HttpTestingController } from '@angular/common/http/testing';

import { SettingsPage } from './settings';
import { DeviceConfig, ForecastConfig, StatsConfig } from '../../core/models';

function statsConfig(over: Partial<StatsConfig> = {}): StatsConfig {
  return {
    tariff: {
      currency: 'GBP',
      standing_charge: 0.6075,
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
      providers: [provideRouter([]), provideHttpClient(), provideHttpClientTesting()],
    }).compileComponents();
    http = TestBed.inject(HttpTestingController);
  });

  /** Flush the tariff + forecast config the page loads on init. */
  function flushConfig(over: Partial<StatsConfig> = {}): void {
    http.expectOne('/api/stats/config').flush(statsConfig(over));
    http.expectOne('/api/forecast/config').flush(forecastConfig());
  }

  /** Flush the serial-port + profile lookups the page loads on init. */
  function flushDeviceLookups(): void {
    http.expectOne('/api/serial-ports').flush({ ports: [{ device: '/dev/ttyUSB0', description: 'USB', hwid: '' }] });
    http.expectOne('/api/profiles').flush({ profiles: [{ name: 'sunsynk-8k-sg05lp1', vendor: 'sunsynk', model: 'X', label: 'sunsynk X' }] });
  }

  it('saveLocale() persists the locale via /api/preferences (T093)', () => {
    const fixture = TestBed.createComponent(SettingsPage);
    fixture.componentInstance.reloadApp = () => {}; // don't navigate in tests
    fixture.detectChanges();
    http.expectOne('/api/devices').flush({ devices: [] });
    flushConfig();

    fixture.componentInstance.localeChoice = 'en-GB';
    fixture.componentInstance.saveLocale();

    const req = http.expectOne('/api/preferences');
    expect(req.request.method).toBe('PUT');
    expect(req.request.body).toEqual({ locale: 'en-GB' });
    req.flush({ locale: 'en-GB' });
    expect(fixture.componentInstance.localeSaved()).toBe(true);
  });

  it('calibratePr() fetches a suggestion and pre-fills the performance ratio (T096)', () => {
    const fixture = TestBed.createComponent(SettingsPage);
    fixture.detectChanges();
    http.expectOne('/api/devices').flush({ devices: [] });
    flushConfig();

    fixture.componentInstance.calibratePr();
    http.expectOne((r) => r.url === '/api/forecast/calibrate').flush({
      device_id: 'd1', current_pr: 0.85, expected_wh: 1000, actual_wh: 800, suggested_pr: 0.68,
    });
    expect(fixture.componentInstance.forecast.site.performance_ratio).toBe(0.68);
    expect(fixture.componentInstance.calibrateMsg()?.cls).toBe('info');
  });

  it('calibratePr() reports when there is not enough data', () => {
    const fixture = TestBed.createComponent(SettingsPage);
    fixture.detectChanges();
    http.expectOne('/api/devices').flush({ devices: [] });
    flushConfig();
    fixture.componentInstance.calibratePr();
    http.expectOne((r) => r.url === '/api/forecast/calibrate').flush({
      device_id: 'd1', current_pr: 0.85, expected_wh: 0, actual_wh: 0, suggested_pr: null,
    });
    expect(fixture.componentInstance.calibrateMsg()?.cls).toBe('secondary');
  });

  it('restore() POSTs the chosen backup file to /api/restore', () => {
    const fixture = TestBed.createComponent(SettingsPage);
    fixture.detectChanges();
    http.expectOne('/api/devices').flush({ devices: [] });
    flushConfig();

    const file = new File([new Uint8Array([1, 2, 3])], 'backup.sqlite');
    const input = { files: [file] } as unknown as HTMLInputElement;
    fixture.componentInstance.restore(input);

    const req = http.expectOne('/api/restore');
    expect(req.request.method).toBe('POST');
    expect(req.request.body instanceof FormData).toBe(true);
    req.flush({ ok: true });
    expect(fixture.componentInstance.restoreMsg()?.cls).toBe('success');
    http.expectOne('/api/devices').flush({ devices: [] }); // refresh() after restore
  });

  it('restore() warns when no file is chosen', () => {
    const fixture = TestBed.createComponent(SettingsPage);
    fixture.detectChanges();
    http.expectOne('/api/devices').flush({ devices: [] });
    flushConfig();
    fixture.componentInstance.restore({ files: [] } as unknown as HTMLInputElement);
    expect(fixture.componentInstance.restoreMsg()?.cls).toBe('warning');
    http.expectNone('/api/restore');
  });

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
    fixture.componentInstance.submitDevice();

    const post = http.expectOne((r) => r.method === 'POST' && r.url === '/api/devices');
    expect(post.request.body).toMatchObject({ id: 'd2', transport: 'dummy' });
    post.flush(device({ id: 'd2' }));

    // refresh after create
    http.expectOne((r) => r.method === 'GET' && r.url === '/api/devices').flush({ devices: [device({ id: 'd2' })] });
    fixture.detectChanges();
    expect(fixture.componentInstance.devices().length).toBe(1);
  });

  it('edits an existing device: loads all fields into the form and PUTs the changes', () => {
    const fixture = TestBed.createComponent(SettingsPage);
    fixture.detectChanges();
    const existing = device({
      id: 'inv', name: 'Inverter', transport: 'modbus_tcp', profile: 'sunsynk-8k-sg05lp1',
      params: { host: '192.168.1.50', port: 502, slave_id: 3 },
    });
    http.expectOne('/api/devices').flush({ devices: [existing] });
    flushConfig();

    const c = fixture.componentInstance;
    c.startEdit(existing);
    expect(c.editingId()).toBe('inv');
    // Every field is populated from the stored config (not just the name).
    expect(c.form).toMatchObject({ id: 'inv', name: 'Inverter', transport: 'modbus_tcp',
      profile: 'sunsynk-8k-sg05lp1', host: '192.168.1.50', tcpPort: 502, slaveId: 3 });

    c.form.host = '192.168.1.99'; // change a non-name field
    c.submitDevice();
    const put = http.expectOne((r) => r.method === 'PUT' && r.url === '/api/devices/inv');
    expect(put.request.body).toMatchObject({
      transport: 'modbus_tcp', profile: 'sunsynk-8k-sg05lp1',
      params: { host: '192.168.1.99', port: 502, slave_id: 3 },
    });
    put.flush(existing);
    http.expectOne((r) => r.method === 'GET' && r.url === '/api/devices').flush({ devices: [existing] });
    expect(c.editingId()).toBeNull(); // form reset after save
  });

  it('shows an inline error on 409', () => {
    const fixture = TestBed.createComponent(SettingsPage);
    fixture.detectChanges();
    http.expectOne('/api/devices').flush({ devices: [] });
    flushConfig();

    fixture.componentInstance.form.id = 'dup';
    fixture.componentInstance.submitDevice();
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
    const t = fixture.componentInstance.tariff;
    expect(t.currency).toBe('GBP');
    expect(t.standingCharge).toBe(0.6075);
    expect(t.importMode).toBe('flat'); // no windows ⇒ flat
    expect(t.importFlat).toBe(0.3);
    expect(t.exportRate).toBe(0.15);
    expect(t.co2Intensity).toBe(200);
  });

  it('loads a time-of-use import schedule into HH:MM windows', () => {
    const fixture = TestBed.createComponent(SettingsPage);
    fixture.detectChanges();
    http.expectOne('/api/devices').flush({ devices: [] });
    flushConfig({
      tariff: {
        currency: 'GBP', standing_charge: 0.6075,
        import_rate: {
          flat: 0.293,
          windows: [
            { start_hour: 0, end_hour: 6, rate: 0.09 },
            { start_hour: 6, end_hour: 0, rate: 0.293 },
          ],
        },
        export_rate: { flat: 0.175, windows: [] },
        seasons: [],
      },
    });
    fixture.detectChanges();
    const t = fixture.componentInstance.tariff;
    expect(t.importMode).toBe('tou');
    expect(t.importWindows).toEqual([
      { start: '00:00', end: '06:00', rate: 0.09 },
      { start: '06:00', end: '00:00', rate: 0.293 },
    ]);
    expect(t.exportRate).toBe(0.175);
  });

  it('saveTariff() PUTs a flat import rate as a bare number + standing charge (T052)', () => {
    const fixture = TestBed.createComponent(SettingsPage);
    fixture.detectChanges();
    http.expectOne('/api/devices').flush({ devices: [] });
    flushConfig();

    fixture.componentInstance.tariff = {
      currency: 'EUR', standingCharge: 0.5, importMode: 'flat', importFlat: 0.4,
      importWindows: [], exportRate: 0.2, co2Intensity: 150, systemCost: 6000,
    };
    fixture.componentInstance.saveTariff();

    const put = http.expectOne((r) => r.method === 'PUT' && r.url === '/api/stats/config');
    expect(put.request.body).toEqual({
      tariff: { currency: 'EUR', standing_charge: 0.5, import_rate: 0.4, export_rate: 0.2 },
      economics: { co2_intensity_g_per_kwh: 150, system_cost: 6000 },
    });
    put.flush(statsConfig());
    fixture.detectChanges();
    expect(fixture.componentInstance.tariffSaved()).toBe(true);
  });

  it('saveTariff() PUTs TOU windows as {flat, windows} with hour-floats', () => {
    const fixture = TestBed.createComponent(SettingsPage);
    fixture.detectChanges();
    http.expectOne('/api/devices').flush({ devices: [] });
    flushConfig();

    // The user's real Octopus-style tariff: cheap overnight, pricier by day.
    fixture.componentInstance.tariff = {
      currency: 'GBP', standingCharge: 0.6075, importMode: 'tou', importFlat: 0.293,
      importWindows: [
        { start: '00:00', end: '06:00', rate: 0.09 },
        { start: '06:00', end: '00:00', rate: 0.293 },
      ],
      exportRate: 0.175, co2Intensity: 200, systemCost: 5000,
    };
    fixture.componentInstance.saveTariff();

    const put = http.expectOne((r) => r.method === 'PUT' && r.url === '/api/stats/config');
    expect(put.request.body).toEqual({
      tariff: {
        currency: 'GBP', standing_charge: 0.6075,
        import_rate: {
          flat: 0.293,
          windows: [
            { start_hour: 0, end_hour: 6, rate: 0.09 },
            { start_hour: 6, end_hour: 0, rate: 0.293 },
          ],
        },
        export_rate: 0.175,
      },
      economics: { co2_intensity_g_per_kwh: 200, system_cost: 5000 },
    });
    put.flush(statsConfig());
    fixture.detectChanges();
    expect(fixture.componentInstance.tariffSaved()).toBe(true);
  });

  it('addWindow/removeWindow manage the TOU window list', () => {
    const fixture = TestBed.createComponent(SettingsPage);
    fixture.detectChanges();
    http.expectOne('/api/devices').flush({ devices: [] });
    flushConfig();
    const c = fixture.componentInstance;
    c.addWindow();
    c.addWindow();
    expect(c.tariff.importWindows.length).toBe(2);
    c.removeWindow(0);
    expect(c.tariff.importWindows.length).toBe(1);
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

  it('loads serial ports and profiles into dropdowns on init', () => {
    const fixture = TestBed.createComponent(SettingsPage);
    fixture.detectChanges();
    http.expectOne('/api/devices').flush({ devices: [] });
    flushConfig();
    flushDeviceLookups();
    expect(fixture.componentInstance.serialPorts().length).toBe(1);
    expect(fixture.componentInstance.serialPorts()[0].device).toBe('/dev/ttyUSB0');
    expect(fixture.componentInstance.profiles()[0].name).toBe('sunsynk-8k-sg05lp1');
  });

  it('refreshPorts() re-fetches /api/serial-ports', () => {
    const fixture = TestBed.createComponent(SettingsPage);
    fixture.detectChanges();
    http.expectOne('/api/devices').flush({ devices: [] });
    flushConfig();
    flushDeviceLookups();

    fixture.componentInstance.refreshPorts();
    http.expectOne('/api/serial-ports').flush({ ports: [] });
    expect(fixture.componentInstance.serialPorts().length).toBe(0);
  });

  it('testConnection() POSTs the form to /api/devices/test and shows the result', () => {
    const fixture = TestBed.createComponent(SettingsPage);
    fixture.detectChanges();
    http.expectOne('/api/devices').flush({ devices: [] });
    flushConfig();
    flushDeviceLookups();

    fixture.componentInstance.form.transport = 'modbus_rtu';
    fixture.componentInstance.form.profile = 'sunsynk-8k-sg05lp1';
    fixture.componentInstance.form.port = '/dev/ttyUSB0';
    fixture.componentInstance.testConnection();

    const post = http.expectOne((r) => r.method === 'POST' && r.url === '/api/devices/test');
    expect(post.request.body).toEqual({
      transport: 'modbus_rtu',
      profile: 'sunsynk-8k-sg05lp1',
      params: { port: '/dev/ttyUSB0', baudrate: 9600, slave_id: 1 },
    });
    post.flush({ ok: true, message: 'Connected — read 12 metric(s).', metric_count: 12 });
    expect(fixture.componentInstance.testResult()?.ok).toBe(true);
    expect(fixture.componentInstance.testing()).toBe(false);
  });

  it('defaults to the Devices tab and renders the tab bar', () => {
    const fixture = TestBed.createComponent(SettingsPage);
    fixture.detectChanges();
    http.expectOne('/api/devices').flush({ devices: [device({ name: 'My Inverter' })] });
    flushConfig();
    fixture.detectChanges();

    expect(fixture.componentInstance.tab()).toBe('devices');
    const tabs = (fixture.nativeElement as HTMLElement).querySelectorAll('.nav-tabs .nav-link');
    expect(tabs.length).toBe(7); // + Dashboards tab (T_DB6)
    // The default (Devices) tab content is rendered; the tariff card is not.
    expect((fixture.nativeElement as HTMLElement).textContent).toContain('My Inverter');
    expect((fixture.nativeElement as HTMLElement).textContent).not.toContain('Import pricing');
  });

  it('reflects the active tab in the URL and restores it from a query param', async () => {
    const router = TestBed.inject(Router);
    const fixture = TestBed.createComponent(SettingsPage);
    fixture.detectChanges();
    http.expectOne('/api/devices').flush({ devices: [] });
    flushConfig();

    // Clicking a tab pushes it to the URL.
    fixture.componentInstance.selectTab('tariff');
    await fixture.whenStable();
    expect(router.url).toContain('tab=tariff');

    // A refresh/back landing on ?tab=solar restores that tab.
    await router.navigate([], { queryParams: { tab: 'solar' } });
    expect(fixture.componentInstance.tab()).toBe('solar');

    // An unknown tab falls back to devices.
    await router.navigate([], { queryParams: { tab: 'bogus' } });
    expect(fixture.componentInstance.tab()).toBe('devices');
  });

  it('switches tabs — selecting Tariff reveals its card', () => {
    const fixture = TestBed.createComponent(SettingsPage);
    fixture.detectChanges();
    http.expectOne('/api/devices').flush({ devices: [] });
    flushConfig();
    fixture.detectChanges();

    fixture.componentInstance.tab.set('tariff');
    fixture.detectChanges();
    expect((fixture.nativeElement as HTMLElement).textContent).toContain('Import pricing');
  });

  it('builds SolarmanV5 device params + gates Test on host/serial (L01)', () => {
    const fixture = TestBed.createComponent(SettingsPage);
    fixture.detectChanges();
    http.expectOne('/api/devices').flush({ devices: [] });
    flushConfig();

    const c = fixture.componentInstance;
    c.form.transport = 'solarman_v5';
    c.form.profile = 'sunsynk-8k-sg05lp1';
    expect(c.canTest()).toBe(false); // no host/serial yet
    c.form.host = '192.168.1.50';
    c.form.serial = '1234567890';
    expect(c.canTest()).toBe(true);
    expect((c as unknown as { deviceParams(): Record<string, unknown> }).deviceParams()).toEqual({
      host: '192.168.1.50', serial: '1234567890', port: 8899, slave_id: 1,
    });
  });

  it('builds Modbus-TCP device params + gates Test on profile/host (L19)', () => {
    const fixture = TestBed.createComponent(SettingsPage);
    fixture.detectChanges();
    http.expectOne('/api/devices').flush({ devices: [] });
    flushConfig();

    const c = fixture.componentInstance;
    c.form.transport = 'modbus_tcp';
    expect(c.canTest()).toBe(false); // needs profile + host
    c.form.profile = 'sunsynk-8k-sg05lp1';
    c.form.host = '192.168.1.50';
    expect(c.canTest()).toBe(true);
    expect((c as unknown as { deviceParams(): Record<string, unknown> }).deviceParams()).toEqual({
      host: '192.168.1.50', port: 502, slave_id: 1,
    });
  });

  it('builds sa_mqtt device params + gates Test on host only, no profile (L20)', () => {
    const fixture = TestBed.createComponent(SettingsPage);
    fixture.detectChanges();
    http.expectOne('/api/devices').flush({ devices: [] });
    flushConfig();

    const c = fixture.componentInstance;
    c.form.transport = 'sa_mqtt';
    expect(c.canTest()).toBe(false); // needs a broker host
    c.form.host = '10.0.0.2';
    expect(c.canTest()).toBe(true); // no register profile required
    expect((c as unknown as { deviceParams(): Record<string, unknown> }).deviceParams()).toEqual({
      host: '10.0.0.2', port: 1883, username: '', password: '', base_topic: 'solar_assistant',
      include_all: false,
    });
  });

  it('embeds the Diagnostics page on the Diagnostics tab (loads its own data)', () => {
    const fixture = TestBed.createComponent(SettingsPage);
    fixture.detectChanges();
    http.expectOne('/api/devices').flush({ devices: [] });
    flushConfig();

    // Not rendered until the tab is opened — no diagnostics request yet.
    http.expectNone('/api/diagnostics');

    fixture.componentInstance.tab.set('diagnostics');
    fixture.detectChanges();
    // The embedded DiagnosticsPage fires its own loads on init.
    http.expectOne('/api/diagnostics').flush({
      version: '9.9', schema_version: 1, poll_interval_s: 3, control_enabled: false,
      database: { path: ':memory:', size_bytes: 1024 },
      rollup: { lag_s: 0 }, alerts: { active_count: 0 }, devices: [],
    });
    http.expectOne((r) => r.url === '/api/grid-events').flush({ events: [] });
    fixture.detectChanges();
    expect((fixture.nativeElement as HTMLElement).querySelector('app-diagnostics')).toBeTruthy();
  });

  it('saveMqtt() PUTs the broker config to /api/integrations/mqtt (L07)', () => {
    const fixture = TestBed.createComponent(SettingsPage);
    fixture.detectChanges();
    http.expectOne('/api/devices').flush({ devices: [] });
    flushConfig();

    fixture.componentInstance.mqtt = {
      enabled: true, host: 'broker.lan', port: 1883, username: 'u', password: 'p', tls: false,
      base_topic: 'solarvolt', interval_s: 30, discovery: true, discovery_prefix: 'homeassistant',
    };
    fixture.componentInstance.saveMqtt();

    const put = http.expectOne((r) => r.method === 'PUT' && r.url === '/api/integrations/mqtt');
    expect(put.request.body).toMatchObject({ enabled: true, host: 'broker.lan', discovery: true });
    put.flush(fixture.componentInstance.mqtt);
    expect(fixture.componentInstance.mqttMsg()?.cls).toBe('success');
  });

  it('testMqtt() POSTs to the test endpoint and reports the published count (L07)', () => {
    const fixture = TestBed.createComponent(SettingsPage);
    fixture.detectChanges();
    http.expectOne('/api/devices').flush({ devices: [] });
    flushConfig();

    fixture.componentInstance.testMqtt();
    const post = http.expectOne((r) => r.method === 'POST' && r.url === '/api/integrations/mqtt/test');
    post.flush({ ok: true, published: 8 });
    expect(fixture.componentInstance.mqttMsg()?.text).toContain('8');
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
