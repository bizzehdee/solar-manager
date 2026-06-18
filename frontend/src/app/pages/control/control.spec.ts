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
          {
            key: 'grid_type', label: 'Grid type', type: 'enum', writable: false,
            options: [{ value: 0, label: 'Single phase' }],
          },
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
      globals: { timer_enabled: true, grid_charge: true, work_mode: 2, max_sell_power_w: 8000, grid_type: 0 },
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
    // Non-repeating sections fill the 2-column grid first (schema order), then the repeating
    // timer spans full width below — so the timer header comes last.
    const headers = Array.from(el.querySelectorAll('.card-header')).map((h) => h.textContent?.trim());
    expect(headers).toEqual(['Globals', 'Battery', 'Timer slots']);
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

  // --- Phase 6 editing (control enabled) ---
  function settingsCtl(): DeviceSettingsResponse {
    return {
      ...settings(),
      control_enabled: true,
      etag: 'abc',
      info: { vendor: 'sunsynk', model: 'SG05LP1', serial: 'SN123', firmware: { protocol: '2.1' } },
    };
  }

  function bootEditable() {
    const fixture = TestBed.createComponent(ControlPage);
    fixture.detectChanges();
    http.expectOne('/api/devices').flush({ devices: [device({ control: true })] });
    http.expectOne('/api/devices/d1/settings/schema').flush(schema());
    http.expectOne('/api/devices/d1/settings').flush(settingsCtl());
    http.expectOne((r) => r.url === '/api/audit').flush({ entries: [] });
    fixture.detectChanges();
    return fixture;
  }

  it('renders the read-only Inverter info card from device identity', () => {
    const fixture = bootEditable();
    const el = fixture.nativeElement as HTMLElement;
    expect(el.textContent).toContain('Inverter info');
    expect(el.textContent).toContain('sunsynk');
    expect(el.textContent).toContain('SG05LP1');
    expect(el.textContent).toContain('SN123');
    expect(el.textContent).toContain('2.1'); // firmware entry
  });

  it('shows edit controls only when control is enabled', () => {
    const fixture = bootEditable();
    const el = fixture.nativeElement as HTMLElement;
    expect(el.textContent).toContain('Editing is enabled');
    expect(el.querySelectorAll('button').length).toBeGreaterThan(0);
    expect(Array.from(el.querySelectorAll('button')).some((b) => b.textContent?.includes('Edit'))).toBe(true);
  });

  it('builds a current→proposed diff and only sends changed fields, with If-Match', () => {
    const fixture = bootEditable();
    const c = fixture.componentInstance;
    const globals = c.schema()!.sections[0];

    c.startEdit(globals, null);
    c.setDraft('max_sell_power_w', 5000); // changed
    c.review(globals, null);
    fixture.detectChanges();

    // Confirm dialog shows exactly the one changed field.
    expect(c.confirm()!.rows.length).toBe(1);
    expect((fixture.nativeElement as HTMLElement).querySelector('.modal')).toBeTruthy();

    c.applyConfirmed();
    const req = http.expectOne('/api/devices/d1/settings');
    expect(req.request.method).toBe('PUT');
    expect(req.request.body).toEqual({ section: 'globals', index: null, values: { max_sell_power_w: 5000 } });
    expect(req.request.headers.get('If-Match')).toBe('abc');
    req.flush({
      device_id: 'd1', ok: true, section: 'globals', index: null,
      changes: { max_sell_power_w: { old: 8000, new: 5000 } }, mismatches: [], etag: 'def',
      values: { ...settings().values, globals: { timer_enabled: true, grid_charge: true, work_mode: 2, max_sell_power_w: 5000 } },
    });
    http.expectOne((r) => r.url === '/api/audit').flush({ entries: [] });
    fixture.detectChanges();

    expect(c.feedback()!.cls).toBe('success');
    expect(c.confirm()).toBeNull();
    expect(c.edit()).toBeNull();
    expect((c.values()!.values['globals'] as Record<string, unknown>)['max_sell_power_w']).toBe(5000);
    expect(c.values()!.etag).toBe('def');
  });

  it('surfaces a read-back mismatch (409) as a rollback warning and reloads device state', () => {
    const fixture = bootEditable();
    const c = fixture.componentInstance;
    const globals = c.schema()!.sections[0];
    c.startEdit(globals, null);
    c.setDraft('max_sell_power_w', 5000);
    c.review(globals, null);
    c.applyConfirmed();

    http.expectOne('/api/devices/d1/settings').flush(
      {
        device_id: 'd1', ok: false, section: 'globals', index: null, changes: {},
        mismatches: ['max_sell_power_w'], etag: 'zzz',
        values: { ...settings().values },
      },
      { status: 409, statusText: 'Conflict' },
    );
    http.expectOne((r) => r.url === '/api/audit').flush({ entries: [] });
    fixture.detectChanges();

    expect(c.feedback()!.cls).toBe('danger');
    expect(c.feedback()!.text).toContain('max_sell_power_w');
    expect(c.values()!.etag).toBe('zzz');
  });

  it('does not render an edit control for a read-only field', () => {
    const fixture = bootEditable();
    const c = fixture.componentInstance;
    const globals = c.schema()!.sections[0];
    c.startEdit(globals, null);
    fixture.detectChanges();

    // 4 writable globals fields ⇒ 4 inputs; the read-only grid_type stays a value display.
    const el = fixture.nativeElement as HTMLElement;
    expect(el.querySelectorAll('app-setting-input').length).toBe(4);
    expect(el.textContent).toContain('Single phase'); // read-only value still shown
  });

  it('reloads (does not clobber) on a stale 412', () => {
    const fixture = bootEditable();
    const c = fixture.componentInstance;
    const globals = c.schema()!.sections[0];
    c.startEdit(globals, null);
    c.setDraft('max_sell_power_w', 5000);
    c.review(globals, null);
    c.applyConfirmed();

    http.expectOne('/api/devices/d1/settings').flush(
      { detail: { error: 'stale', current_etag: 'newer' } },
      { status: 412, statusText: 'Precondition Failed' },
    );
    // handleWriteError → load(): re-fetches schema + settings (+ audit on settings success).
    http.expectOne('/api/devices/d1/settings/schema').flush(schema());
    http.expectOne('/api/devices/d1/settings').flush(settingsCtl());
    http.expectOne((r) => r.url === '/api/audit').flush({ entries: [] });
    fixture.detectChanges();

    expect(c.feedback()!.cls).toBe('warning');
    expect(c.edit()).toBeNull();
  });

  // --- timer end_time virtual field ---

  it('injects an End column into the timer-slots table header', () => {
    const fixture = bootEditable();
    const el = fixture.nativeElement as HTMLElement;
    const tables = Array.from(el.querySelectorAll('table'));
    const slotTable = tables.find((t) => t.querySelector('thead'))!;
    const headers = Array.from(slotTable.querySelectorAll('thead th')).map((th) => th.textContent?.trim());
    expect(headers).toContain('End');
    // End comes right after Start
    const startIdx = headers.indexOf('Start');
    expect(headers[startIdx + 1]).toBe('End');
  });

  it('shows each slot end time as the next slot start time, wrapping the last to slot 1', () => {
    // Give each slot a distinct start_time so the wrapping is observable.
    const fixture = TestBed.createComponent(ControlPage);
    fixture.detectChanges();
    http.expectOne('/api/devices').flush({ devices: [device({ control: true })] });
    http.expectOne('/api/devices/d1/settings/schema').flush(schema());
    const startTimes = ['00:05', '05:55', '09:00', '13:00', '17:00', '21:00'];
    const slotValues = startTimes.map((t) => ({ start_time: t, power_w: 8000, target_soc_pct: 10, charge_from_grid: false }));
    http.expectOne('/api/devices/d1/settings').flush({ ...settings(), control_enabled: true, etag: 'abc', values: { ...settings().values, timer_slots: slotValues } });
    http.expectOne((r) => r.url === '/api/audit').flush({ entries: [] });
    fixture.detectChanges();

    const c = fixture.componentInstance;
    const timerSection = c.fullWidthSections()[0];
    // End time of slot i = start_time of slot i+1; last slot wraps to slot 0.
    for (let i = 0; i < 6; i++) {
      const row = c.rowsFor(timerSection)[i];
      const endTime = c.rowValue(timerSection, i, { key: 'end_time', label: 'End', type: 'time' }, row);
      expect(endTime).toBe(startTimes[(i + 1) % 6]);
    }
  });

  it('initialises end_time in the draft from the next slot start_time', () => {
    const fixture = bootEditable();
    const c = fixture.componentInstance;
    const timerSection = c.fullWidthSections()[0]; // timer_slots with end_time injected

    c.startEditRow(timerSection, 0);
    // All slots share '00:05' in the default fixture, so end_time = slot 1 start_time = '00:05'.
    expect(c.draft()['end_time']).toBe('00:05');

    // Last slot wraps to slot 0.
    c.cancelEdit();
    c.startEditRow(timerSection, 5);
    expect(c.draft()['end_time']).toBe('00:05');
  });

  it('dispatches a single write to the NEXT slot when only end_time changes', () => {
    const fixture = bootEditable();
    const c = fixture.componentInstance;
    const timerSection = c.fullWidthSections()[0];

    c.startEditRow(timerSection, 0);
    c.setDraft('end_time', '06:00'); // change only end_time
    c.review(timerSection, 0);
    fixture.detectChanges();

    expect(c.confirm()!.nextSlotIndex).toBe(1);
    expect(c.confirm()!.rows.length).toBe(1);
    expect(c.confirm()!.rows[0].field.key).toBe('end_time');

    c.applyConfirmed();
    // No primary write (nothing else changed) — goes directly to slot 1's start_time.
    const req = http.expectOne('/api/devices/d1/settings');
    expect(req.request.method).toBe('PUT');
    expect(req.request.body).toEqual({ section: 'timer_slots', index: 1, values: { start_time: '06:00' } });
    expect(req.request.headers.get('If-Match')).toBe('abc');
    req.flush({ device_id: 'd1', ok: true, section: 'timer_slots', index: 1, changes: {}, mismatches: [], etag: 'def', values: settings().values });
    http.expectOne((r) => r.url === '/api/audit').flush({ entries: [] });
    fixture.detectChanges();

    expect(c.feedback()!.cls).toBe('success');
    expect(c.edit()).toBeNull();
  });

  it('dispatches two sequential writes when slot fields and end_time both change', () => {
    const fixture = bootEditable();
    const c = fixture.componentInstance;
    const timerSection = c.fullWidthSections()[0];

    c.startEditRow(timerSection, 2); // slot 3 (index 2)
    c.setDraft('power_w', 4000);
    c.setDraft('end_time', '09:00');
    c.review(timerSection, 2);
    fixture.detectChanges();

    expect(c.confirm()!.nextSlotIndex).toBe(3);
    expect(c.confirm()!.rows.length).toBe(2);

    c.applyConfirmed();

    // First: primary write for slot 2 (power_w only — end_time stripped out).
    const req1 = http.expectOne('/api/devices/d1/settings');
    expect(req1.request.body).toEqual({ section: 'timer_slots', index: 2, values: { power_w: 4000 } });
    req1.flush({ device_id: 'd1', ok: true, section: 'timer_slots', index: 2, changes: {}, mismatches: [], etag: 'def2', values: settings().values });

    // Second: cascade write to slot 3 start_time, using the etag from the first response.
    const req2 = http.expectOne('/api/devices/d1/settings');
    expect(req2.request.body).toEqual({ section: 'timer_slots', index: 3, values: { start_time: '09:00' } });
    expect(req2.request.headers.get('If-Match')).toBe('def2');
    req2.flush({ device_id: 'd1', ok: true, section: 'timer_slots', index: 3, changes: {}, mismatches: [], etag: 'def3', values: settings().values });
    http.expectOne((r) => r.url === '/api/audit').flush({ entries: [] });
    fixture.detectChanges();

    expect(c.feedback()!.cls).toBe('success');
  });

  it('wraps the last slot end_time to slot 1 (nextSlotIndex = 0)', () => {
    const fixture = bootEditable();
    const c = fixture.componentInstance;
    const timerSection = c.fullWidthSections()[0];

    c.startEditRow(timerSection, 5); // last slot
    c.setDraft('end_time', '23:30');
    c.review(timerSection, 5);

    expect(c.confirm()!.nextSlotIndex).toBe(0); // wraps to slot 0
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
