import { TestBed } from '@angular/core/testing';
import type { GridStackNode } from 'gridstack';

import { DashboardHost, mergeLayout } from './dashboard-host';
import { DashboardConfig, DashboardWidget } from '../core/models';

describe('mergeLayout', () => {
  const widgets: DashboardWidget[] = [
    { type: 'energy-flow', x: 0, y: 0, w: 6, h: 6, config: {} },
    { type: 'metric-gauge', x: 6, y: 0, w: 2, h: 2, config: { metric: 'battery_soc_pct' } },
  ];

  it('maps saved nodes back onto widgets by gs-id, preserving type + config', () => {
    const nodes: GridStackNode[] = [
      { id: '1', x: 0, y: 0, w: 2, h: 2 },
      { id: '0', x: 0, y: 2, w: 6, h: 6 },
    ];
    const out = mergeLayout(widgets, nodes);
    // Sorted by (y, x): the metric-gauge (now at 0,0) comes before the energy-flow (now at 0,2).
    expect(out[0].type).toBe('metric-gauge');
    expect(out[0].config).toEqual({ metric: 'battery_soc_pct' });
    expect(out[0]).toMatchObject({ x: 0, y: 0, w: 2, h: 2 });
    expect(out[1].type).toBe('energy-flow');
    expect(out[1]).toMatchObject({ x: 0, y: 2, w: 6, h: 6 });
  });

  it('drops nodes whose id does not match a widget', () => {
    const out = mergeLayout(widgets, [{ id: '99', x: 0, y: 0, w: 2, h: 2 }]);
    expect(out).toEqual([]);
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
});
