import { TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting, HttpTestingController } from '@angular/common/http/testing';

import { ControlPage } from './control';
import { DeviceConfig, DeviceSettingsResponse, SettingsSchemaResponse } from '../../core/models';

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
    capabilities: ['read'],
    control: false,
    settings: true,
    ...over,
  };
}

function schema(): SettingsSchemaResponse {
  return {
    device_id: 'd1',
    supported: true,
    sections: [
      {
        key: 'globals',
        label: 'Globals',
        repeating: false,
        fields: [
          { key: 'timer_enabled', label: 'Timer enabled', type: 'bool' },
          { key: 'grid_charge', label: 'Grid charge', type: 'bool' },
          {
            key: 'work_mode',
            label: 'Work mode',
            type: 'enum',
            options: [
              { value: 0, label: 'Selling first' },
              { value: 2, label: 'Zero export to CT' },
            ],
          },
          { key: 'max_sell_power_w', label: 'Max sell power', type: 'number', unit: 'W' },
        ],
      },
      {
        key: 'timer_slots',
        label: 'Timer slots',
        repeating: true,
        count: 6,
        fields: [
          { key: 'start_time', label: 'Start', type: 'time' },
          { key: 'power_w', label: 'Power', type: 'number', unit: 'W' },
          { key: 'target_soc_pct', label: 'Target SoC', type: 'number', unit: '%' },
          { key: 'charge_from_grid', label: 'Charge from grid', type: 'bool' },
        ],
      },
      {
        key: 'battery',
        label: 'Battery',
        repeating: false,
        fields: [
          { key: 'float_voltage_v', label: 'Float voltage', type: 'number', unit: 'V' },
          { key: 'max_charge_current_a', label: 'Max charge current', type: 'number', unit: 'A' },
        ],
      },
    ],
  };
}

function settings(): DeviceSettingsResponse {
  const slot = {
    start_time: '00:05',
    power_w: 8000,
    target_soc_pct: 65,
    charge_from_grid: true,
  };
  return {
    device_id: 'd1',
    supported: true,
    values: {
      globals: { timer_enabled: true, grid_charge: true, work_mode: 2, max_sell_power_w: 8000 },
      timer_slots: Array.from({ length: 6 }, () => ({ ...slot })),
      battery: { float_voltage_v: 53.6, max_charge_current_a: 140 },
    },
  };
}

describe('ControlPage', () => {
  let http: HttpTestingController;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [ControlPage],
      providers: [provideHttpClient(), provideHttpClientTesting()],
    }).compileComponents();
    http = TestBed.inject(HttpTestingController);
  });

  afterEach(() => http.verify());

  it('fetches devices then the schema + settings for the first settings device', () => {
    const fixture = TestBed.createComponent(ControlPage);
    fixture.detectChanges();
    http.expectOne('/api/devices').flush({ devices: [device()] });

    http.expectOne('/api/devices/d1/settings/schema').flush(schema());
    http.expectOne('/api/devices/d1/settings').flush(settings());
    fixture.detectChanges();

    const el = fixture.nativeElement as HTMLElement;
    expect(el.textContent).toContain('Read-only');
    // One card per section.
    const headers = Array.from(el.querySelectorAll('.card-header')).map((h) => h.textContent?.trim());
    expect(headers).toEqual(['Globals', 'Timer slots', 'Battery']);
  });

  it('renders the repeating timer-slots table with one row per entry', () => {
    const fixture = TestBed.createComponent(ControlPage);
    fixture.detectChanges();
    http.expectOne('/api/devices').flush({ devices: [device()] });
    http.expectOne('/api/devices/d1/settings/schema').flush(schema());
    http.expectOne('/api/devices/d1/settings').flush(settings());
    fixture.detectChanges();

    const el = fixture.nativeElement as HTMLElement;
    // The timer-slots card is the repeating one with 6 rows.
    const tables = Array.from(el.querySelectorAll('table'));
    const slotTable = tables.find((t) => t.querySelector('thead'));
    expect(slotTable).toBeTruthy();
    expect(slotTable!.querySelectorAll('tbody tr').length).toBe(6);
    expect(slotTable!.textContent).toContain('Slot 1');
    expect(slotTable!.textContent).toContain('00:05'); // time as-is
  });

  it('renders an enum as its option label, bools as Yes/No, and numbers with units', () => {
    const fixture = TestBed.createComponent(ControlPage);
    fixture.detectChanges();
    http.expectOne('/api/devices').flush({ devices: [device()] });
    http.expectOne('/api/devices/d1/settings/schema').flush(schema());
    http.expectOne('/api/devices/d1/settings').flush(settings());
    fixture.detectChanges();

    const text = (fixture.nativeElement as HTMLElement).textContent ?? '';
    expect(text).toContain('Zero export to CT'); // work_mode 2 → label
    expect(text).toContain('Yes'); // timer_enabled true
    expect(text).toContain('8000 W'); // max_sell_power_w with unit
    expect(text).toContain('53.6 V'); // float_voltage_v with unit
  });

  it('shows the "no settings" alert when the schema is unsupported', () => {
    const fixture = TestBed.createComponent(ControlPage);
    fixture.detectChanges();
    http.expectOne('/api/devices').flush({ devices: [device()] });
    http.expectOne('/api/devices/d1/settings/schema').flush({ device_id: 'd1', supported: false, sections: [] });
    http.expectOne('/api/devices/d1/settings').flush({ device_id: 'd1', supported: false, values: {} });
    fixture.detectChanges();

    const el = fixture.nativeElement as HTMLElement;
    expect(el.textContent).toContain('This device exposes no settings.');
    expect(el.querySelectorAll('.card-header').length).toBe(0);
  });
});
