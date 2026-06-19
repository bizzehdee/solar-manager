import { TestBed } from '@angular/core/testing';

import { EnergyFlow, EdgeId, FlowRole, computeEnergyFlow } from './energy-flow';
import { MetricValue } from '../core/models';

// The gnarly bit is the pure metric → {ring colour, flow direction} mapping (plan.md §21):
// sign conventions, the house-always-grey rule, and offline suppression. Test it directly,
// then a few DOM checks that the component renders rings + active-edge flow groups.

describe('computeEnergyFlow (pure mapping)', () => {
  const edge = (m: ReturnType<typeof computeEnergyFlow>, id: EdgeId) => m.edges.find((e) => e.id === id)!;

  it('midday: solar producing, battery charging, exporting → greens, flow toward battery/grid', () => {
    const m = computeEnergyFlow(
      { pv_power_w: 6500, battery_power_w: 3000, grid_power_w: -2000, load_power_w: 1200 },
      true,
    );
    expect(m.solar).toBe('success');
    expect(m.battery).toBe('success'); // charging
    expect(m.grid).toBe('success'); //    exporting
    expect(m.house).toBe('secondary'); // always grey
    expect(m.inverter).toBe('success');

    expect(edge(m, 'solar')).toMatchObject({ active: true, toInverter: true, role: 'success' });
    // Charging flows inverter→battery; exporting flows inverter→grid.
    expect(edge(m, 'battery')).toMatchObject({ active: true, toInverter: false, role: 'success' });
    expect(edge(m, 'grid')).toMatchObject({ active: true, toInverter: false, role: 'success' });
    expect(edge(m, 'house')).toMatchObject({ active: true, toInverter: false, role: 'secondary' });
  });

  it('evening: no solar, battery discharging, grid idle → battery red flowing to inverter', () => {
    const m = computeEnergyFlow(
      { pv_power_w: 0, battery_power_w: -2500, grid_power_w: 0, load_power_w: 2400 },
      true,
    );
    expect(m.solar).toBe('secondary'); // idle
    expect(m.battery).toBe('danger'); //  discharging
    expect(m.grid).toBe('secondary'); //  idle
    expect(edge(m, 'solar').active).toBe(false);
    expect(edge(m, 'battery')).toMatchObject({ active: true, toInverter: true, role: 'danger' });
    expect(edge(m, 'grid').active).toBe(false);
    expect(edge(m, 'house').active).toBe(true); // load present
  });

  it('night import: grid red flowing to inverter, house consuming', () => {
    const m = computeEnergyFlow({ pv_power_w: 0, battery_power_w: 0, grid_power_w: 1800, load_power_w: 1800 }, true);
    expect(m.grid).toBe('danger'); // importing
    expect(edge(m, 'grid')).toMatchObject({ active: true, toInverter: true, role: 'danger' });
    expect(edge(m, 'house')).toMatchObject({ active: true, toInverter: false });
  });

  it('inverter offline: centre ring red and every flow suppressed (still colours the nodes)', () => {
    const m = computeEnergyFlow({ pv_power_w: 6500, battery_power_w: 3000, grid_power_w: -2000, load_power_w: 1200 }, false);
    expect(m.inverter).toBe('danger');
    expect(m.solar).toBe('success'); // node state still reflects production…
    expect(m.edges.every((e) => !e.active)).toBe(true); // …but nothing flows through a dead inverter
  });

  it('house is always grey regardless of load', () => {
    expect(computeEnergyFlow({ load_power_w: 5000 }, true).house).toBe('secondary');
    expect(computeEnergyFlow({ load_power_w: 0 }, true).house).toBe('secondary');
    expect(computeEnergyFlow(null, true).house).toBe('secondary');
  });

  it('treats sub-1W magnitudes as idle (missing ≠ zero ≠ flowing)', () => {
    const m = computeEnergyFlow({ pv_power_w: 0.5, battery_power_w: -0.4, grid_power_w: 0.2, load_power_w: 0 }, true);
    expect(m.solar).toBe('secondary');
    expect(m.battery).toBe('secondary');
    expect(m.grid).toBe('secondary');
    expect(m.edges.every((e) => !e.active)).toBe(true);
  });

  it('handles a null/empty snapshot without throwing', () => {
    const m = computeEnergyFlow(null, true);
    expect(m.edges.map((e) => e.id).sort()).toEqual(['battery', 'grid', 'house', 'solar']);
    expect(m.edges.every((e) => !e.active)).toBe(true);
  });
});

describe('EnergyFlow component', () => {
  beforeEach(async () => {
    await TestBed.configureTestingModule({ imports: [EnergyFlow] }).compileComponents();
  });

  function mount(metrics: Record<string, MetricValue> | null, inverterOnline = true) {
    const fixture = TestBed.createComponent(EnergyFlow);
    fixture.componentRef.setInput('metrics', metrics);
    fixture.componentRef.setInput('inverterOnline', inverterOnline);
    fixture.detectChanges();
    return fixture.nativeElement as HTMLElement;
  }

  it('renders five nodes and four connector wires', () => {
    const el = mount({ pv_power_w: 3000, load_power_w: 1000 });
    expect(el.querySelectorAll('.ef-node').length).toBe(5);
    expect(el.querySelectorAll('.ef-wire').length).toBe(4);
  });

  it('colours each node ring by status via the Bootstrap CSS variable', () => {
    const el = mount({ pv_power_w: 3000, battery_power_w: -1500, grid_power_w: 1200, load_power_w: 2000 });
    const colour = (sel: string) => (el.querySelector(sel) as HTMLElement).style.color;
    expect(colour('.ef-node--solar')).toContain('--bs-success'); // producing
    expect(colour('.ef-node--battery')).toContain('--bs-danger'); // discharging
    expect(colour('.ef-node--grid')).toContain('--bs-danger'); //    importing
    expect(colour('.ef-node--house')).toContain('--bs-secondary'); // always grey
    expect(colour('.ef-node--inverter')).toContain('--bs-success'); // online
  });

  it('renders a flow group only for active edges', () => {
    // Solar producing + house load active = 2 active edges; battery/grid idle.
    const el = mount({ pv_power_w: 4000, battery_power_w: 0, grid_power_w: 0, load_power_w: 2500 });
    const active = Array.from(el.querySelectorAll('.ef-edge')).map((g) => g.getAttribute('data-edge'));
    expect(active.sort()).toEqual(['house', 'solar']);
    expect(el.querySelectorAll('.ef-edge[data-edge="solar"] .ef-chevron').length).toBe(3);
  });

  it('shows no flow groups when the inverter is offline', () => {
    const el = mount({ pv_power_w: 4000, load_power_w: 2500 }, false);
    expect(el.querySelectorAll('.ef-edge').length).toBe(0);
    expect((el.querySelector('.ef-node--inverter') as HTMLElement).style.color).toContain('--bs-danger');
  });
});
