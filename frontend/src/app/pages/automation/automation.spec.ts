import { TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting, HttpTestingController } from '@angular/common/http/testing';

import { AutomationPage } from './automation';
import { AutomationOptions, AutomationPreview, AutomationRule } from '../../core/models';

function health(automation_enabled: boolean) {
  return { version: '9.9', devices: [], poll_interval_s: 3, status: 'ok', control_enabled: false, automation_enabled };
}

const OPTIONS: AutomationOptions = {
  condition_kinds: ['day_of_week', 'metric', 'tariff_window'],
  ops: ['lt', 'gt'],
  metrics: ['battery_soc_pct'],
  match_modes: ['all', 'any'],
  targets: [
    { section: 'timer_slots', section_label: 'Work-mode timer', field: 'target_soc_pct', label: 'Target SoC', type: 'number', repeating: true, count: 6, status: 'ok' },
    { section: 'battery_type', section_label: 'Battery', field: 'battery_capacity_ah', label: 'Capacity', type: 'number', repeating: false, count: null, status: 'at_risk' },
  ],
};

function rule(over: Partial<AutomationRule> = {}): AutomationRule {
  return {
    id: 'weekend', name: 'Weekend top-up', match: 'all', priority: 1, enabled: false,
    conditions: [{ kind: 'day_of_week', params: { days: [5, 6] } }],
    actions: [{ target: { section: 'timer_slots', field: 'target_soc_pct', index: 1 }, value: 80, enabled: true }],
    ...over,
  };
}

function preview(): AutomationPreview {
  return {
    device_id: 'dummy', now: '2026-06-20T14:00:00+00:00', rule_count: 1,
    decision: {
      changes: [{ rule_id: 'weekend', rule_name: 'Weekend top-up', priority: 1,
        target: { section: 'timer_slots', field: 'target_soc_pct', index: 1 }, value: 80,
        active: true, status: 'ok', will_apply: true }],
      overridden: [],
    },
  };
}

describe('AutomationPage', () => {
  let http: HttpTestingController;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [AutomationPage],
      providers: [provideHttpClient(), provideHttpClientTesting()],
    }).compileComponents();
    http = TestBed.inject(HttpTestingController);
  });

  afterEach(() => http.verify());

  function boot(enabled = true) {
    const fixture = TestBed.createComponent(AutomationPage);
    fixture.detectChanges();
    http.expectOne('/api/health').flush(health(enabled));
    if (enabled) {
      http.expectOne('/api/automation/options').flush(OPTIONS);
      http.expectOne('/api/automation/rules').flush({ rules: [rule()] });
      http.expectOne((r) => r.url === '/api/automation/preview').flush(preview());
    }
    fixture.detectChanges();
    return fixture;
  }

  it('shows the disabled notice when automation is off (no further calls)', () => {
    const fixture = TestBed.createComponent(AutomationPage);
    fixture.detectChanges();
    http.expectOne('/api/health').flush(health(false));
    fixture.detectChanges();
    expect((fixture.nativeElement as HTMLElement).textContent).toContain('Automation is disabled');
  });

  it('lists rules and renders the live preview when enabled', () => {
    const fixture = boot();
    const el = fixture.nativeElement as HTMLElement;
    expect(el.textContent).toContain('Weekend top-up');
    expect(el.textContent).toContain('timer_slots[1].target_soc_pct');
    expect(el.textContent).toContain('would apply');
  });

  it('toggles a rule armed flag via PUT then reloads', () => {
    const fixture = boot();
    fixture.componentInstance.toggleRule(rule());
    const put = http.expectOne((r) => r.method === 'PUT' && r.url === '/api/automation/rules/weekend');
    expect(put.request.body.enabled).toBe(true);
    put.flush(rule({ enabled: true }));
    http.expectOne('/api/automation/rules').flush({ rules: [rule({ enabled: true })] });
    http.expectOne((r) => r.url === '/api/automation/preview').flush(preview());
  });

  it('builds and saves a new rule with a slugged id', () => {
    const fixture = boot();
    fixture.componentInstance.newRule();
    const e = fixture.componentInstance.editing()!;
    e.name = 'Cheap charge';
    fixture.componentInstance.addCondition();
    fixture.componentInstance.addAction();
    fixture.componentInstance.saveRule();

    const put = http.expectOne((r) => r.method === 'PUT' && r.url === '/api/automation/rules/cheap_charge');
    expect(put.request.body.name).toBe('Cheap charge');
    expect(put.request.body.actions.length).toBe(1);
    put.flush(rule({ id: 'cheap_charge' }));
    http.expectOne('/api/automation/rules').flush({ rules: [] });
    http.expectOne((r) => r.url === '/api/automation/preview').flush(preview());
    expect(fixture.componentInstance.editing()).toBeNull();
  });

  it('rejects a blank rule name without calling the API', () => {
    const fixture = boot();
    fixture.componentInstance.newRule();
    fixture.componentInstance.saveRule();
    expect(fixture.componentInstance.formError()).toContain('Name is required');
  });

  it('setKind resets condition params to the kind defaults', () => {
    const fixture = boot();
    fixture.componentInstance.newRule();
    const e = fixture.componentInstance.editing()!;
    fixture.componentInstance.addCondition();
    const cond = e.conditions[0];
    fixture.componentInstance.setKind(cond, 'metric');
    expect(cond.kind).toBe('metric');
    expect(cond.params['op']).toBe('lt');
    expect(cond.params['metric']).toBe('battery_soc_pct');
  });
});
