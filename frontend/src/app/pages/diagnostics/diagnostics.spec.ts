import { TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting, HttpTestingController } from '@angular/common/http/testing';

import { DiagnosticsPage } from './diagnostics';
import { Diagnostics } from '../../core/models';

function diag(over: Partial<Diagnostics> = {}): Diagnostics {
  return {
    version: '0.0', schema_version: 5, control_enabled: false, poll_interval_s: 3,
    database: { path: 'solarvolt.db', size_bytes: 2_500_000 },
    rollup: { watermark_ts: 1_700_000_000, lag_s: 42 },
    alerts: { active_count: 1 },
    network: null,
    devices: [
      { device_id: 'dummy', vendor: 'dummy', model: 'Sim', online: true, last_sample_age_s: 2, comms: null },
      { device_id: 'inv', vendor: 'sunsynk', model: 'SG05LP1', online: true, last_sample_age_s: 1,
        comms: { transactions: 10, failures: 1, retries: 2, last_rtt_ms: 35, last_error: 'timeout' } },
    ],
    ...over,
  };
}

describe('DiagnosticsPage', () => {
  let http: HttpTestingController;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [DiagnosticsPage],
      providers: [provideHttpClient(), provideHttpClientTesting()],
    }).compileComponents();
    http = TestBed.inject(HttpTestingController);
  });

  afterEach(() => http.verify());

  it('renders build/DB/rollup summary and the device comms table', () => {
    const fixture = TestBed.createComponent(DiagnosticsPage);
    fixture.detectChanges();
    http.expectOne('/api/diagnostics').flush(diag());
    http.expectOne((r) => r.url === '/api/grid-events').flush({ events: [] });
    fixture.detectChanges();

    const text = (fixture.nativeElement as HTMLElement).textContent ?? '';
    expect(text).toContain('v5'); // schema version
    expect(text).toContain('2.4 MB'); // 2,500,000 bytes humanised
    expect(text).toContain('42'); // rollup lag
    expect(text).toContain('10 / 1 / 2'); // comms tx/fail/retry for the modbus device
    expect(text).toContain('— (no wire)'); // dummy has no comms
    expect(text).toContain('timeout'); // last error surfaced
    expect(text).toContain('No grid loss/return events'); // empty grid timeline
  });

  it('renders the host Wi-Fi network card with SSID + signal', () => {
    const fixture = TestBed.createComponent(DiagnosticsPage);
    fixture.detectChanges();
    http.expectOne('/api/diagnostics').flush(diag({
      network: {
        interface: 'wlan0', ip: '192.168.1.42', type: 'wifi', status: 'up',
        wifi: { ssid: 'MyHomeWiFi', signal_dbm: -48, signal_pct: 96, link_quality: 62 },
        ethernet: null,
      },
    }));
    http.expectOne((r) => r.url === '/api/grid-events').flush({ events: [] });
    fixture.detectChanges();
    const text = (fixture.nativeElement as HTMLElement).textContent ?? '';
    expect(text).toContain('Host network');
    expect(text).toContain('192.168.1.42');
    expect(text).toContain('MyHomeWiFi');
    expect(text).toContain('96%');
    expect(text).toContain('-48 dBm');
  });

  it('renders the host Ethernet network card with link speed', () => {
    const fixture = TestBed.createComponent(DiagnosticsPage);
    fixture.detectChanges();
    http.expectOne('/api/diagnostics').flush(diag({
      network: {
        interface: 'eth0', ip: '10.0.0.5', type: 'ethernet', status: 'up',
        wifi: null, ethernet: { name: 'eth0', link_speed_mbps: 1000 },
      },
    }));
    http.expectOne((r) => r.url === '/api/grid-events').flush({ events: [] });
    fixture.detectChanges();
    const text = (fixture.nativeElement as HTMLElement).textContent ?? '';
    expect(text).toContain('eth0');
    expect(text).toContain('1000 Mbps');
  });

  it('renders the grid-outage timeline when events exist', () => {
    const fixture = TestBed.createComponent(DiagnosticsPage);
    fixture.detectChanges();
    http.expectOne('/api/diagnostics').flush(diag());
    http.expectOne((r) => r.url === '/api/grid-events').flush({
      events: [
        { ts: 1_700_000_500, device_id: 'inv', event: 'outage_end' },
        { ts: 1_700_000_000, device_id: 'inv', event: 'outage_start' },
      ],
    });
    fixture.detectChanges();
    const text = (fixture.nativeElement as HTMLElement).textContent ?? '';
    expect(text).toContain('grid lost');
    expect(text).toContain('grid restored');
  });

  it('shows inverter clock drift and syncs to system time', () => {
    const fixture = TestBed.createComponent(DiagnosticsPage);
    fixture.detectChanges();
    http.expectOne('/api/diagnostics').flush(diag({
      devices: [
        { device_id: 'inv', vendor: 'sunsynk', model: 'SG05LP1', online: true, last_sample_age_s: 1,
          comms: null, clock: { supported: true, device_time: '2026-06-21T12:01:35', drift_s: 95, syncable: true } },
      ],
    }));
    http.expectOne((r) => r.url === '/api/grid-events').flush({ events: [] });
    fixture.detectChanges();

    const el = fixture.nativeElement as HTMLElement;
    expect(el.textContent).toContain('+95 s'); // drift under 2 min shown in seconds

    // Click Sync → POST, then the component reloads the snapshot.
    (el.querySelector('button.btn-link') as HTMLButtonElement).click();
    http.expectOne((r) => r.url === '/api/devices/inv/clock/sync' && r.method === 'POST').flush({ ok: true, drift_s: 0 });
    http.expectOne('/api/diagnostics').flush(diag({
      devices: [
        { device_id: 'inv', vendor: 'sunsynk', model: 'SG05LP1', online: true, last_sample_age_s: 1,
          comms: null, clock: { supported: true, device_time: '2026-06-21T12:02:00', drift_s: 0, syncable: true } },
      ],
    }));
    http.expectOne((r) => r.url === '/api/grid-events').flush({ events: [] });
    fixture.detectChanges();
    expect((fixture.nativeElement as HTMLElement).textContent).toContain('in sync');
  });

  it('driftLabel humanises seconds, minutes, and the in-sync/unknown cases', () => {
    const c = TestBed.createComponent(DiagnosticsPage).componentInstance;
    expect(c.driftLabel(null)).toBe('—');
    expect(c.driftLabel(0)).toBe('in sync');
    expect(c.driftLabel(95)).toBe('+95 s');
    expect(c.driftLabel(-180)).toBe('−3 min');
    expect(c.driftWarn(95)).toBe(true);
    expect(c.driftWarn(5)).toBe(false);
  });

  it('humanBytes formats sizes', () => {
    const c = TestBed.createComponent(DiagnosticsPage).componentInstance;
    expect(c.humanBytes(512)).toBe('512 B');
    expect(c.humanBytes(2048)).toBe('2.0 KB');
    expect(c.humanBytes(5 * 1024 * 1024)).toBe('5.0 MB');
  });
});
