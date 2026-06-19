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

  // --- Rules tab (L11) -------------------------------------------------------
  function openRules(fixture: ReturnType<typeof TestBed.createComponent<AlertsPage>>) {
    fixture.detectChanges();
    flush([], 0); // initial inbox load
    fixture.componentInstance.showRules();
    http.expectOne('/api/alert-rules/options').flush({
      metrics: ['battery_soc_pct', '__stale_s__', '__fault_count__'],
      ops: ['lt', 'le', 'gt', 'ge', 'eq', 'ne'], severities: ['info', 'warning', 'critical'], channels: ['webhook'],
    });
    http.expectOne('/api/devices').flush({ devices: [] });
    http.expectOne('/api/alert-rules').flush({
      rules: [{ id: 'low_soc', name: 'Low SoC', metric: 'battery_soc_pct', op: 'lt', threshold: 20,
        hysteresis: 5, debounce_s: 60, severity: 'warning', channels: [], quiet_hours: null,
        device_id: null, message: '', enabled: true }],
    });
    fixture.detectChanges();
  }

  it('lists rules and renders the metric/op/threshold summary', () => {
    const fixture = TestBed.createComponent(AlertsPage);
    openRules(fixture);
    const el = fixture.nativeElement as HTMLElement;
    expect(el.textContent).toContain('Low SoC');
    expect(el.textContent).toContain('battery_soc_pct < 20');
  });

  it('creates a new rule (PUT) with an id slugged from the name', () => {
    const fixture = TestBed.createComponent(AlertsPage);
    openRules(fixture);

    fixture.componentInstance.newRule();
    const e = fixture.componentInstance.editing()!;
    e.name = 'Hot Inverter';
    e.metric = '__fault_count__';
    e.op = 'gt';
    e.threshold = 0;
    fixture.componentInstance.save();

    const req = http.expectOne((r) => r.method === 'PUT' && r.url === '/api/alert-rules/hot_inverter');
    expect(req.request.body.name).toBe('Hot Inverter');
    expect(req.request.body.metric).toBe('__fault_count__');
    req.flush(req.request.body);
    http.expectOne('/api/alert-rules').flush({ rules: [] }); // reload after save
    expect(fixture.componentInstance.editing()).toBeNull();
  });

  it('rejects a blank name without hitting the API', () => {
    const fixture = TestBed.createComponent(AlertsPage);
    openRules(fixture);
    fixture.componentInstance.newRule();
    fixture.componentInstance.save();
    expect(fixture.componentInstance.formError()).toContain('Name is required');
    http.verify(); // no PUT issued
  });

  it('toggles a rule enabled flag via PUT', () => {
    const fixture = TestBed.createComponent(AlertsPage);
    openRules(fixture);
    const rule = fixture.componentInstance.rules()[0];
    fixture.componentInstance.toggle(rule);
    const req = http.expectOne((r) => r.method === 'PUT' && r.url === '/api/alert-rules/low_soc');
    expect(req.request.body.enabled).toBe(false);
    req.flush(req.request.body);
    http.expectOne('/api/alert-rules').flush({ rules: [] });
  });

  it('deletes a rule then reloads', () => {
    const fixture = TestBed.createComponent(AlertsPage);
    openRules(fixture);
    fixture.componentInstance.remove(fixture.componentInstance.rules()[0]);
    http.expectOne((r) => r.method === 'DELETE' && r.url === '/api/alert-rules/low_soc').flush(null);
    http.expectOne('/api/alert-rules').flush({ rules: [] });
  });
});
