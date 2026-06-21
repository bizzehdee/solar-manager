import { TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting, HttpTestingController } from '@angular/common/http/testing';

import { ApiService } from './api.service';
import { DailyStats, DeviceConfig, ForecastConfig, ForecastResponse, HistoryResponse, StatsConfig } from './models';

describe('ApiService', () => {
  let api: ApiService;
  let http: HttpTestingController;

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [provideHttpClient(), provideHttpClientTesting()],
    });
    api = TestBed.inject(ApiService);
    http = TestBed.inject(HttpTestingController);
  });

  afterEach(() => http.verify());

  it('getHistoryMetrics() with device scopes by device_id', () => {
    api.getHistoryMetrics('dev1').subscribe((res) => {
      expect(res.metrics).toEqual(['pv_power_w']);
    });
    const req = http.expectOne((r) => r.url === '/api/history/metrics');
    expect(req.request.params.get('device_id')).toBe('dev1');
    req.flush({ device_id: 'dev1', metrics: ['pv_power_w'] });
  });

  it('getHistory() builds params and omits undefined', () => {
    api.getHistory({ metric: 'pv_power_w', resolution: '1h', start: 100 }).subscribe();
    const req = http.expectOne((r) => r.url === '/api/history');
    expect(req.request.params.get('metric')).toBe('pv_power_w');
    expect(req.request.params.get('resolution')).toBe('1h');
    expect(req.request.params.get('start')).toBe('100');
    expect(req.request.params.has('end')).toBe(false);
    expect(req.request.params.has('device_id')).toBe(false);
    const body: HistoryResponse = {
      device_id: 'dev1',
      metric: 'pv_power_w',
      resolution: '1h',
      start: 100,
      end: 200,
      points: [{ ts: 100, value: 5 }],
    };
    req.flush(body);
  });

  it('getDevices() GETs /api/devices', () => {
    api.getDevices().subscribe((res) => expect(res.devices.length).toBe(1));
    const req = http.expectOne('/api/devices');
    expect(req.request.method).toBe('GET');
    req.flush({ devices: [sampleDevice()] });
  });

  it('createDevice() POSTs the body', () => {
    const body = { id: 'd2', transport: 'dummy' };
    api.createDevice(body).subscribe();
    const req = http.expectOne('/api/devices');
    expect(req.request.method).toBe('POST');
    expect(req.request.body).toEqual(body);
    req.flush(sampleDevice());
  });

  it('updateDevice() PUTs to the id URL', () => {
    api.updateDevice('d1', { enabled: false }).subscribe();
    const req = http.expectOne('/api/devices/d1');
    expect(req.request.method).toBe('PUT');
    expect(req.request.body).toEqual({ enabled: false });
    req.flush(sampleDevice());
  });

  it('deleteDevice() DELETEs the id URL', () => {
    api.deleteDevice('d1').subscribe();
    const req = http.expectOne('/api/devices/d1');
    expect(req.request.method).toBe('DELETE');
    req.flush(null);
  });

  it('getDeviceSettingsSchema() GETs the schema URL and parses sections', () => {
    api.getDeviceSettingsSchema('d1').subscribe((res) => {
      expect(res.supported).toBe(true);
      expect(res.sections[0].key).toBe('globals');
    });
    const req = http.expectOne('/api/devices/d1/settings/schema');
    expect(req.request.method).toBe('GET');
    req.flush({
      device_id: 'd1',
      supported: true,
      sections: [{ key: 'globals', label: 'Globals', repeating: false, fields: [] }],
    });
  });

  it('getDeviceSettings() GETs the settings URL and parses values', () => {
    api.getDeviceSettings('d1').subscribe((res) => {
      expect(res.supported).toBe(true);
      expect(res.values['globals']).toEqual({ work_mode: 2 });
    });
    const req = http.expectOne('/api/devices/d1/settings');
    expect(req.request.method).toBe('GET');
    req.flush({ device_id: 'd1', supported: true, values: { globals: { work_mode: 2 } } });
  });

  it('getDailyStats() with no args GETs /api/stats/daily without params', () => {
    api.getDailyStats().subscribe((res) => expect(res.currency).toBe('GBP'));
    const req = http.expectOne((r) => r.url === '/api/stats/daily');
    expect(req.request.params.has('device_id')).toBe(false);
    expect(req.request.params.has('date')).toBe(false);
    req.flush(sampleDailyStats());
  });

  it('getDailyStats() sets device_id and date params', () => {
    api.getDailyStats('dev1', '2026-06-18').subscribe();
    const req = http.expectOne((r) => r.url === '/api/stats/daily');
    expect(req.request.params.get('device_id')).toBe('dev1');
    expect(req.request.params.get('date')).toBe('2026-06-18');
    req.flush(sampleDailyStats());
  });

  it('getStatsConfig() GETs /api/stats/config', () => {
    api.getStatsConfig().subscribe((res) => expect(res.tariff.currency).toBe('GBP'));
    const req = http.expectOne('/api/stats/config');
    expect(req.request.method).toBe('GET');
    req.flush(sampleStatsConfig());
  });

  it('putStatsConfig() PUTs the body to /api/stats/config', () => {
    const body = {
      tariff: { import_rate: 0.3, export_rate: 0.15, currency: 'GBP' },
      economics: { co2_intensity_g_per_kwh: 200, system_cost: 5000 },
    };
    api.putStatsConfig(body).subscribe();
    const req = http.expectOne('/api/stats/config');
    expect(req.request.method).toBe('PUT');
    expect(req.request.body).toEqual(body);
    req.flush(sampleStatsConfig());
  });

  it('getForecast() with no args GETs /api/forecast without params', () => {
    api.getForecast().subscribe((res) => expect(res.expected_today_wh).toBe(12000));
    const req = http.expectOne((r) => r.url === '/api/forecast');
    expect(req.request.method).toBe('GET');
    expect(req.request.params.has('device_id')).toBe(false);
    req.flush(sampleForecast());
  });

  it('getForecast() sets the device_id param', () => {
    api.getForecast('dev1').subscribe();
    const req = http.expectOne((r) => r.url === '/api/forecast');
    expect(req.request.params.get('device_id')).toBe('dev1');
    req.flush(sampleForecast());
  });

  it('getForecast() sets the days param for a multi-day horizon', () => {
    api.getForecast(undefined, 7).subscribe();
    const req = http.expectOne((r) => r.url === '/api/forecast');
    expect(req.request.params.get('days')).toBe('7');
    expect(req.request.params.has('device_id')).toBe(false);
    req.flush(sampleForecast());
  });

  it('getForecastConfig() GETs /api/forecast/config', () => {
    api.getForecastConfig().subscribe((res) => expect(res.arrays.length).toBe(1));
    const req = http.expectOne('/api/forecast/config');
    expect(req.request.method).toBe('GET');
    req.flush(sampleForecastConfig());
  });

  it('putForecastConfig() PUTs the body to /api/forecast/config', () => {
    const body = sampleForecastConfig();
    api.putForecastConfig(body).subscribe();
    const req = http.expectOne('/api/forecast/config');
    expect(req.request.method).toBe('PUT');
    expect(req.request.body).toEqual(body);
    req.flush(sampleForecastConfig());
  });

  // --- Notification channels (L10) + readings webhook (L09) ---
  it('getAlertChannels()/putAlertChannels()/testAlertChannel() hit the channel URLs', () => {
    api.getAlertChannels().subscribe((r) => expect(r.configured).toEqual(['webhook:h']));
    http.expectOne('/api/alert-channels').flush({
      channels: { webhooks: [{ id: 'h', url: 'http://h', enabled: true }] },
      configured: ['webhook:h'], supported: ['telegram'], webhook_labels: { 'webhook:h': 'H' },
    });

    const body = { telegram: { bot_token: 'T', chat_id: '1' }, webhooks: [] };
    api.putAlertChannels(body).subscribe();
    const put = http.expectOne('/api/alert-channels');
    expect(put.request.method).toBe('PUT');
    expect(put.request.body).toEqual(body);
    put.flush({ channels: body, configured: ['telegram'], supported: ['telegram'], webhook_labels: {} });

    // A webhook channel name carries a colon — it must reach the test URL intact.
    api.testAlertChannel('webhook:h').subscribe((r) => expect(r.ok).toBe(true));
    const test = http.expectOne('/api/alert-channels/webhook:h/test');
    expect(test.request.method).toBe('POST');
    test.flush({ ok: true });
  });

  it('automation rule CRUD + options/preview hit the automation URLs', () => {
    api.getAutomationRules().subscribe((r) => expect(r.rules).toEqual([]));
    http.expectOne('/api/automation/rules').flush({ rules: [] });

    const body = { name: 'Weekend', match: 'all', conditions: [], actions: [] };
    api.putAutomationRule('weekend', body).subscribe();
    const put = http.expectOne('/api/automation/rules/weekend');
    expect(put.request.method).toBe('PUT');
    expect(put.request.body).toEqual(body);
    put.flush({ ...body, id: 'weekend', priority: 0, enabled: false });

    api.deleteAutomationRule('weekend').subscribe();
    const del = http.expectOne('/api/automation/rules/weekend');
    expect(del.request.method).toBe('DELETE');
    del.flush(null);

    api.getAutomationOptions('dev1').subscribe();
    const opts = http.expectOne((r) => r.url === '/api/automation/options');
    expect(opts.request.params.get('device_id')).toBe('dev1');
    opts.flush({ condition_kinds: [], ops: [], metrics: [], match_modes: [], channels: [], targets: [] });

    api.getAutomationPreview().subscribe((p) => expect(p.rule_count).toBe(0));
    http.expectOne((r) => r.url === '/api/automation/preview')
      .flush({ device_id: 'dummy', now: 't', rule_count: 0, decision: { changes: [], overridden: [] } });

    api.applyAutomation().subscribe((r) => expect(r.applied.length).toBe(0));
    const apply = http.expectOne((r) => r.url === '/api/automation/apply');
    expect(apply.request.method).toBe('POST');
    apply.flush({ device_id: 'dummy', now: 't', applied: [], failed: [] });
  });

  it('getReadingsWebhooks()/putReadingsWebhooks()/testReadingsWebhook() hit the integration URLs', () => {
    api.getReadingsWebhooks().subscribe((r) => expect(r.webhooks).toEqual([]));
    http.expectOne('/api/integrations/readings-webhooks').flush({ webhooks: [] });

    const webhooks = [{ id: 'h', label: 'H', url: 'http://hook', method: 'POST', headers: {},
                        content_type: 'application/json', payload_template: '', enabled: true, interval_s: 30 }];
    api.putReadingsWebhooks(webhooks).subscribe();
    const put = http.expectOne('/api/integrations/readings-webhooks');
    expect(put.request.method).toBe('PUT');
    expect(put.request.body).toEqual({ webhooks });
    put.flush({ webhooks });

    api.testReadingsWebhook('h').subscribe((r) => expect(r.sent).toBe(true));
    const test = http.expectOne('/api/integrations/readings-webhooks/h/test');
    expect(test.request.method).toBe('POST');
    test.flush({ ok: true, sent: true });
  });
});

function sampleForecast(): ForecastResponse {
  return {
    device_id: 'd1',
    days: 7,
    generation: [{ ts: 1_700_000_000, pv_w: 4200, ghi: 800, cloud_cover: 20, temp_c: 22 }],
    soc: [{ ts: 1_700_000_000, soc_pct: 65, pv_w: 4200, load_w: 600, battery_w: 3600, grid_w: 0 }],
    daily: [{ date: '2023-11-14', expected_wh: 12000, min_soc_pct: 30, max_soc_pct: 90, battery_depleted: false }],
    depletion_ts: null,
    full_ts: 1_700_010_000,
    expected_today_wh: 12000,
    currency: 'GBP',
  };
}

function sampleForecastConfig(): ForecastConfig {
  return {
    site: { lat: 51.5, lon: -0.12, performance_ratio: 0.85 },
    arrays: [{ name: 'Roof', kwp: 5, tilt: 30, azimuth: 180 }],
    battery: { capacity_wh: 10000, min_soc_pct: 10, max_soc_pct: 100 },
  };
}

function sampleDailyStats(): DailyStats {
  return {
    device_id: 'd1',
    date: '2026-06-18',
    energy_wh: { pv: 1000, load: 800, import: 100, export: 300, charge: 200, discharge: 150 },
    self_consumption_pct: 70,
    self_sufficiency_pct: 88,
    peak_pv_w: 4200,
    round_trip_efficiency: 0.92,
    economics: {
      import_cost: 0.03,
      export_revenue: 0.045,
      standing_charge: 0.6075,
      net_cost: -0.015,
      baseline_cost: 0.24,
      savings: 0.255,
      co2_avoided_kg: 0.2,
    },
    currency: 'GBP',
  };
}

function sampleStatsConfig(): StatsConfig {
  return {
    tariff: {
      currency: 'GBP',
      standing_charge: 0.6075,
      import_rate: { flat: 0.3, windows: [] },
      export_rate: { flat: 0.15, windows: [] },
      seasons: [],
    },
    economics: { co2_intensity_g_per_kwh: 200, system_cost: 5000 },
  };
}

function sampleDevice(): DeviceConfig {
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
    capabilities: ['read'],
    control: false,
  };
}
