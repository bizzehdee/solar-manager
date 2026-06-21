import { TestBed } from '@angular/core/testing';

import { WebhookEndpoint } from '../core/models';
import { WebhookListEditor } from './webhook-list-editor';

function endpoint(over: Partial<WebhookEndpoint> = {}): WebhookEndpoint {
  return {
    id: 'h', label: 'Hook', url: 'http://h', method: 'POST', headers: {},
    content_type: 'application/json', payload_template: '', enabled: true, ...over,
  };
}

describe('WebhookListEditor', () => {
  beforeEach(async () => {
    await TestBed.configureTestingModule({ imports: [WebhookListEditor] }).compileComponents();
  });

  function create(endpoints: WebhookEndpoint[] = [], readings = false) {
    const fixture = TestBed.createComponent(WebhookListEditor);
    fixture.componentRef.setInput('endpoints', endpoints);
    fixture.componentRef.setInput('readings', readings);
    fixture.detectChanges();
    return fixture;
  }

  it('seeds working rows from the endpoints input (headers → editable text)', () => {
    const fixture = create([endpoint({ headers: { Authorization: 'Bearer x' } })]);
    const rows = fixture.componentInstance.rows();
    expect(rows.length).toBe(1);
    expect(rows[0].headersText).toBe('Authorization: Bearer x');
  });

  it('add() appends a blank row; readings rows carry an interval', () => {
    const fixture = create([], true);
    fixture.componentInstance.add();
    const rows = fixture.componentInstance.rows();
    expect(rows.length).toBe(1);
    expect(rows[0].interval_s).toBe(60);
  });

  it('remove() drops the row at the index', () => {
    const fixture = create([endpoint({ id: 'a' }), endpoint({ id: 'b' })]);
    fixture.componentInstance.remove(0);
    expect(fixture.componentInstance.rows().map((r) => r.id)).toEqual(['b']);
  });

  it('emits the cleaned endpoints on save (headers text parsed back to a map)', () => {
    const fixture = create([endpoint()]);
    const saved: WebhookEndpoint[][] = [];
    fixture.componentInstance.save.subscribe((e) => saved.push(e));
    fixture.componentInstance.rows()[0].headersText = 'X-Token: abc\nbad-line';
    fixture.componentInstance.emitSave();
    expect(saved[0][0].headers).toEqual({ 'X-Token': 'abc' });
    expect((saved[0][0] as unknown as Record<string, unknown>)['headersText']).toBeUndefined();
  });

  it('applyPreset() sets the payload template (Slack shape)', () => {
    const fixture = create([endpoint()]);
    const slack = fixture.componentInstance.presets().find((p) => p.label === 'Slack')!;
    fixture.componentInstance.applyPreset(0, slack);
    expect(fixture.componentInstance.rows()[0].payload_template).toContain('"text"');
  });

  it('emits a single endpoint on test', () => {
    const fixture = create([endpoint({ id: 'one' })]);
    const tested: WebhookEndpoint[] = [];
    fixture.componentInstance.test.subscribe((e) => tested.push(e));
    fixture.componentInstance.test.emit(fixture.componentInstance.toEndpoint(fixture.componentInstance.rows()[0]));
    expect(tested[0].id).toBe('one');
  });
});
