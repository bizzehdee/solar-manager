import { TestBed } from '@angular/core/testing';
import type { GridStackNode } from 'gridstack';

import { DashboardHost, mergeLayout } from './dashboard-host';
import { DashboardConfig, DashboardWidget } from '../core/models';

const widgets: DashboardWidget[] = [
  { type: 'energy-flow', x: 0, y: 0, w: 6, h: 6, config: {} },
  { type: 'soc-gauge', x: 6, y: 0, w: 2, h: 2, config: { metric: 'battery_soc_pct' } },
];

const dashboard: DashboardConfig = { id: 'now', name: 'Now', builtin: true, widgets };

describe('mergeLayout', () => {
  it('maps saved nodes back onto widgets by gs-id, preserving type + config', () => {
    const nodes: GridStackNode[] = [
      { id: '1', x: 0, y: 0, w: 2, h: 2 },
      { id: '0', x: 0, y: 2, w: 6, h: 6 },
    ];
    const out = mergeLayout(widgets, nodes);
    // Sorted by (y, x): the soc-gauge (now at 0,0) comes before the energy-flow (now at 0,2).
    expect(out[0].type).toBe('soc-gauge');
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
    const fixture = TestBed.createComponent(DashboardHost);
    fixture.componentRef.setInput('dashboard', dashboard);
    fixture.detectChanges();

    const items = (fixture.nativeElement as HTMLElement).querySelectorAll('.grid-stack-item');
    expect(items.length).toBe(2);

    const first = items[0];
    expect(first.getAttribute('gs-id')).toBe('0');
    expect(first.getAttribute('gs-x')).toBe('0');
    expect(first.getAttribute('gs-w')).toBe('6');
    expect(first.getAttribute('gs-h')).toBe('6');
    expect(first.textContent).toContain('energy-flow');

    expect(items[1].getAttribute('gs-x')).toBe('6');
    expect(items[1].textContent).toContain('soc-gauge');
  });
});
