import { TestBed } from '@angular/core/testing';
import type { GridStackNode } from 'gridstack';

import { DashboardHost, mergeLayout } from './dashboard-host';
import { DashboardConfig, DashboardWidget } from '../core/models';

describe('mergeLayout', () => {
  const widgets: DashboardWidget[] = [
    { type: 'energy-flow', x: 0, y: 0, w: 6, h: 6, config: {} },
    { type: 'metric-gauge', x: 6, y: 0, w: 2, h: 2, config: { metric: 'battery_soc_pct' } },
  ];

  it('applies node positions to widgets by gs-id, preserving order + type + config', () => {
    const nodes: GridStackNode[] = [
      { id: '1', x: 0, y: 0, w: 2, h: 2 },
      { id: '0', x: 0, y: 2, w: 6, h: 6 },
    ];
    const out = mergeLayout(widgets, nodes);
    // Order is preserved (no reorder); each widget gets its matching node's position.
    expect(out[0].type).toBe('energy-flow');
    expect(out[0]).toMatchObject({ x: 0, y: 2, w: 6, h: 6 });
    expect(out[1].type).toBe('metric-gauge');
    expect(out[1].config).toEqual({ metric: 'battery_soc_pct' });
    expect(out[1]).toMatchObject({ x: 0, y: 0, w: 2, h: 2 });
  });

  it('preserves widgets whose id is not in the node set (no drop on partial/empty save)', () => {
    expect(mergeLayout(widgets, [{ id: '99', x: 0, y: 0, w: 2, h: 2 }])).toEqual(widgets);
    expect(mergeLayout(widgets, [])).toEqual(widgets); // empty save must not wipe the layout
  });

  it('falls back to the original position when a node omits a coordinate', () => {
    const out = mergeLayout(widgets, [{ id: '0' }]);
    expect(out[0]).toMatchObject({ x: 0, y: 0, w: 6, h: 6 });
  });
});

describe('DashboardHost', () => {
  beforeEach(async () => {
    await TestBed.configureTestingModule({ imports: [DashboardHost] }).compileComponents();
  });

  it('renders one grid-stack-item per widget with the config grid attributes', () => {
    const widgets: DashboardWidget[] = [
      { type: 'metric-gauge', x: 0, y: 0, w: 2, h: 2, config: { metric: 'battery_soc_pct', unit: '%', max: 100 } },
      { type: 'metric-card', x: 2, y: 0, w: 4, h: 2, config: { metric: 'grid_voltage_v', label: 'Grid V', unit: 'V' } },
    ];
    const fixture = TestBed.createComponent(DashboardHost);
    fixture.componentRef.setInput('dashboard', { id: 'now', name: 'Now', builtin: true, widgets } as DashboardConfig);
    fixture.componentRef.setInput('data', { metrics: { battery_soc_pct: 55, grid_voltage_v: 240 } });
    fixture.detectChanges();

    const root = fixture.nativeElement as HTMLElement;
    const items = root.querySelectorAll('.grid-stack-item');
    expect(items.length).toBe(2);
    expect(items[0].getAttribute('gs-id')).toBe('0');
    expect(items[1].getAttribute('gs-w')).toBe('4');

    // The registry resolved each type → its presentational component.
    expect(root.querySelector('app-power-gauge')).not.toBeNull();
    expect(root.querySelector('app-metric-card')).not.toBeNull();
    // Live data + config flowed through the registry adapter into the metric card.
    expect(root.querySelector('app-metric-card')?.textContent).toContain('Grid V');
    expect(root.querySelector('app-metric-card')?.textContent).toContain('240');
  });

  it('renders a placeholder (not a crash) for an unknown widget type', () => {
    const widgets: DashboardWidget[] = [{ type: 'does-not-exist', x: 0, y: 0, w: 2, h: 2, config: {} }];
    const fixture = TestBed.createComponent(DashboardHost);
    fixture.componentRef.setInput('dashboard', { id: 'x', name: 'X', builtin: false, widgets } as DashboardConfig);
    fixture.detectChanges();
    expect((fixture.nativeElement as HTMLElement).textContent).toContain('Unknown widget: does-not-exist');
  });

  // --- edit mode (T_DB7) ---
  function editFixture() {
    const widgets: DashboardWidget[] = [
      { type: 'metric-card', x: 0, y: 0, w: 2, h: 2, config: { metric: 'pv_power_w', label: 'Solar' } },
    ];
    const fixture = TestBed.createComponent(DashboardHost);
    fixture.componentRef.setInput('dashboard', { id: 'u', name: 'U', builtin: false, widgets } as DashboardConfig);
    fixture.detectChanges();
    return fixture;
  }

  it('adds a widget at its default size', () => {
    const fixture = editFixture();
    const host = fixture.componentInstance;
    host.enterEdit();
    host.addWidget('metric-gauge');
    expect(host.items.length).toBe(2);
    const added = host.items[1];
    expect(added.type).toBe('metric-gauge');
    expect(added.w).toBe(2); // metric-gauge default
  });

  it('removes a widget by index', () => {
    const fixture = editFixture();
    const host = fixture.componentInstance;
    host.enterEdit();
    host.removeAt(0);
    expect(host.items.length).toBe(0);
  });

  it('save emits the current layout', () => {
    const fixture = editFixture();
    const host = fixture.componentInstance;
    let emitted: DashboardWidget[] | undefined;
    host.layoutSaved.subscribe((w) => (emitted = w));
    host.enterEdit();
    host.addWidget('metric-gauge');
    host.save();
    expect(host.editing()).toBe(false);
    expect(emitted?.length).toBe(2);
  });

  it('discard reverts the draft to the loaded dashboard', () => {
    const fixture = editFixture();
    const host = fixture.componentInstance;
    host.enterEdit();
    host.addWidget('metric-gauge');
    expect(host.items.length).toBe(2);
    host.discard();
    expect(host.editing()).toBe(false);
    expect(host.items.length).toBe(1); // back to the original single widget
  });

  function importEvent(text: string): Event {
    const input = document.createElement('input');
    Object.defineProperty(input, 'files', { value: [new File([text], 'd.json', { type: 'application/json' })] });
    return { target: input } as unknown as Event;
  }

  it('imports a layout from JSON and emits it for persistence', async () => {
    const fixture = editFixture();
    const host = fixture.componentInstance;
    let emitted: DashboardWidget[] | undefined;
    host.layoutSaved.subscribe((w) => (emitted = w));
    await host.onImportFile(importEvent(JSON.stringify({
      name: 'X', widgets: [{ type: 'metric-card', x: 0, y: 0, w: 2, h: 1, config: { metric: 'grid_power_w' } }],
    })));
    expect(host.items.length).toBe(1);
    expect(host.items[0].config['metric']).toBe('grid_power_w');
    expect(emitted?.length).toBe(1);
    expect(host.notice()?.cls).toBe('success');
  });

  it('warns (but still imports) when a layout has unknown widget types', async () => {
    const fixture = editFixture();
    const host = fixture.componentInstance;
    await host.onImportFile(importEvent(JSON.stringify({
      name: 'X', widgets: [{ type: 'mystery', x: 0, y: 0, w: 2, h: 2, config: {} }],
    })));
    expect(host.items.length).toBe(1);
    expect(host.notice()?.cls).toBe('warning');
    expect(host.notice()?.text).toContain('mystery');
  });

  it('shows an error notice and keeps the layout on an invalid import file', async () => {
    const fixture = editFixture();
    const host = fixture.componentInstance;
    await host.onImportFile(importEvent('not json at all'));
    expect(host.notice()?.cls).toBe('danger');
    expect(host.items.length).toBe(1); // unchanged
  });

  it('reset emits so the page can drop its override', () => {
    const fixture = editFixture();
    const host = fixture.componentInstance;
    let fired = false;
    host.reset.subscribe(() => (fired = true));
    host.reset.emit();
    expect(fired).toBe(true);
  });

  it('opens widget config in a centred modal (not an inline bottom panel)', () => {
    const fixture = editFixture();
    const host = fixture.componentInstance;
    host.enterEdit();
    host.configure(0);
    fixture.detectChanges();

    const root = fixture.nativeElement as HTMLElement;
    const modal = root.querySelector('.modal.d-block');
    expect(modal).not.toBeNull();
    expect(root.querySelector('.modal-backdrop')).not.toBeNull();
    expect(modal?.textContent).toContain('Configure');

    // "Done" closes it (clears the selection → modal removed).
    (modal!.querySelector('.modal-footer .btn') as HTMLButtonElement).click();
    fixture.detectChanges();
    expect(host.configIndex()).toBeNull();
    expect((fixture.nativeElement as HTMLElement).querySelector('.modal.d-block')).toBeNull();
  });

  it('renders the colour (role) field as a dropdown labelled by actual colour, with a swatch', () => {
    const fixture = editFixture(); // metric-card has a {key:'role', label:'Colour', type:'role'} field
    const host = fixture.componentInstance;
    host.enterEdit();
    host.configure(0);
    fixture.detectChanges();

    const select = (fixture.nativeElement as HTMLElement).querySelector('#cfg-role') as HTMLSelectElement;
    expect(select?.tagName).toBe('SELECT');
    // Values stay the Bootstrap roles (widgets consume them); labels are the actual colours.
    expect(Array.from(select.options).map((o) => o.value)).toEqual(
      expect.arrayContaining(['primary', 'success', 'danger']),
    );
    expect(Array.from(select.options).map((o) => o.textContent?.trim())).toEqual(
      expect.arrayContaining(['Blue', 'Green', 'Red']),
    );
    // A colour swatch sits beside the select as a live example of the choice.
    expect(select.closest('.input-group')?.querySelector('span[style]')).not.toBeNull();
    expect(host.roleColor('success')).toBe('var(--bs-success)');
    expect(host.roleColor('unknown')).toBe('var(--bs-primary)');
  });

  it('renders the icon field as a dropdown with a live icon preview beside it', () => {
    const fixture = editFixture(); // metric-card has a {key:'icon', label:'Icon', type:'icon'} field
    const host = fixture.componentInstance;
    host.enterEdit();
    host.configure(0);
    host.setConfig('icon', 'bi-sun'); // so the preview reflects the chosen icon
    fixture.detectChanges();

    const select = (fixture.nativeElement as HTMLElement).querySelector('#cfg-icon') as HTMLSelectElement;
    expect(select?.tagName).toBe('SELECT');
    expect(Array.from(select.options).map((o) => o.value)).toEqual(
      expect.arrayContaining(['bi-sun', 'bi-battery', 'bi-leaf']),
    );
    // A live <i> preview of the chosen icon sits beside the select.
    const preview = select.closest('.input-group')?.querySelector('i.bi');
    expect(preview?.classList).toContain('bi-sun');
  });

  it('setConfig updates the selected widget config immutably', () => {
    const fixture = editFixture();
    const host = fixture.componentInstance;
    host.enterEdit();
    host.configure(0);
    host.setConfig('label', 'PV');
    expect(host.items[0].config['label']).toBe('PV');
    expect(host.items[0].config['metric']).toBe('pv_power_w'); // others preserved
  });
});
