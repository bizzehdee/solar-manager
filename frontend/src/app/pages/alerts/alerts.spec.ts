import { TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting, HttpTestingController } from '@angular/common/http/testing';

import { AlertsPage } from './alerts';
import { Alert } from '../../core/models';

function alert(over: Partial<Alert> = {}): Alert {
  return {
    id: 1, rule_id: 'low_soc', device_id: 'dummy', severity: 'warning', metric: 'battery_soc_pct',
    value: 12, message: 'Battery SoC is low', fired_at: 1_700_000_000,
    cleared_at: null, acked_at: null, snooze_until: null, ...over,
  };
}

describe('AlertsPage', () => {
  let http: HttpTestingController;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [AlertsPage],
      providers: [provideHttpClient(), provideHttpClientTesting()],
    }).compileComponents();
    http = TestBed.inject(HttpTestingController);
  });

  afterEach(() => http.verify());

  function flush(alerts: Alert[], active_count = alerts.length) {
    http.expectOne((r) => r.url === '/api/alerts').flush({ alerts, active_count });
  }

  it('loads active alerts on init and renders them', () => {
    const fixture = TestBed.createComponent(AlertsPage);
    fixture.detectChanges();
    flush([alert()]);
    fixture.detectChanges();

    const el = fixture.nativeElement as HTMLElement;
    expect(el.textContent).toContain('Battery SoC is low');
    expect(el.textContent).toContain('warning');
    expect(el.querySelector('.list-group-item')).toBeTruthy();
  });

  it('shows the all-clear when there are no active alerts', () => {
    const fixture = TestBed.createComponent(AlertsPage);
    fixture.detectChanges();
    flush([], 0);
    fixture.detectChanges();
    expect((fixture.nativeElement as HTMLElement).textContent).toContain('all clear');
  });

  it('acks an alert then reloads', () => {
    const fixture = TestBed.createComponent(AlertsPage);
    fixture.detectChanges();
    flush([alert({ id: 7 })]);
    fixture.detectChanges();

    fixture.componentInstance.ack(alert({ id: 7 }));
    http.expectOne((r) => r.method === 'POST' && r.url === '/api/alerts/7/ack').flush({ ok: true });
    flush([]); // reload after ack
  });

  it('snoozes an alert (POST with minutes) then reloads', () => {
    const fixture = TestBed.createComponent(AlertsPage);
    fixture.detectChanges();
    flush([alert({ id: 9 })]);
    fixture.detectChanges();

    fixture.componentInstance.snooze(alert({ id: 9 }));
    const req = http.expectOne((r) => r.method === 'POST' && r.url === '/api/alerts/9/snooze');
    expect(req.request.body).toEqual({ minutes: 60 });
    req.flush({ ok: true });
    flush([]);
  });

  it('switches to history (active=false) when toggled', () => {
    const fixture = TestBed.createComponent(AlertsPage);
    fixture.detectChanges();
    http.expectOne((r) => r.url === '/api/alerts' && r.params.get('active') === 'true').flush({ alerts: [], active_count: 0 });
    fixture.detectChanges();

    fixture.componentInstance.setActive(false);
    http.expectOne((r) => r.url === '/api/alerts' && r.params.get('active') === 'false')
      .flush({ alerts: [alert({ cleared_at: 1_700_000_500 })], active_count: 0 });
  });
});
