import { DashboardData } from '../core/models';
import { WIDGET_REGISTRY, widgetDef, unknownWidgetTypes } from './widget-registry';

const data: DashboardData = {
  metrics: { battery_soc_pct: 55, pv_power_w: 3200, grid_power_w: -1500, grid_voltage_v: 240 },
  inverterOnline: true,
  series: { pv_power_w: [{ ts: 1, value: 100 }] },
};

describe('WIDGET_REGISTRY', () => {
  it('declares every L06 widget type with complete sizing metadata', () => {
    const expected = [
      'energy-flow', 'metric-gauge', 'metric-card', 'stat-card', 'time-series-chart',
      'daily-kpis', 'history-chart',
    ];
    expect(Object.keys(WIDGET_REGISTRY).sort()).toEqual([...expected].sort());
    for (const def of Object.values(WIDGET_REGISTRY)) {
      expect(def.component).toBeTruthy();
      expect(def.label).toBeTruthy();
      expect(def.defaultW).toBeGreaterThanOrEqual(def.minW);
      expect(def.defaultH).toBeGreaterThanOrEqual(def.minH);
      expect(Array.isArray(def.configSchema)).toBe(true);
    }
  });

  it('metric-gauge shows the magnitude of a (possibly negative) flow', () => {
    const inputs = WIDGET_REGISTRY['metric-gauge'].inputs({ metric: 'grid_power_w', label: 'Grid', max: 5000 }, data);
    expect(inputs['value']).toBe(1500); // abs(-1500)
    expect(inputs['max']).toBe(5000);
    expect(inputs['label']).toBe('Grid');
    expect(inputs['unit']).toBe('W'); // default unit
  });

  it('metric-gauge can render battery SoC with overridden name/unit/full-scale', () => {
    const inputs = WIDGET_REGISTRY['metric-gauge'].inputs(
      { metric: 'battery_soc_pct', label: 'Charge', unit: '%', max: 100 },
      data,
    );
    expect(inputs['value']).toBe(55);
    expect(inputs['label']).toBe('Charge');
    expect(inputs['unit']).toBe('%');
    expect(inputs['max']).toBe(100);
  });

  it('metric-card maps config + live value, defaulting the label to the metric key', () => {
    const inputs = WIDGET_REGISTRY['metric-card'].inputs({ metric: 'grid_voltage_v', unit: 'V' }, data);
    expect(inputs['value']).toBe(240);
    expect(inputs['unit']).toBe('V');
    expect(inputs['label']).toBe('grid_voltage_v');
  });

  it('metric-card value is undefined (not 0) when the metric is absent', () => {
    const inputs = WIDGET_REGISTRY['metric-card'].inputs({ metric: 'missing' }, data);
    expect(inputs['value']).toBeUndefined();
  });

  it('time-series-chart pulls its points from data.series[metric]', () => {
    const inputs = WIDGET_REGISTRY['time-series-chart'].inputs({ metric: 'pv_power_w' }, data);
    expect((inputs['points'] as unknown[]).length).toBe(1);
    const empty = WIDGET_REGISTRY['time-series-chart'].inputs({ metric: 'none' }, data);
    expect(empty['points']).toEqual([]);
  });

  it('widgetDef returns undefined for an unknown type', () => {
    expect(widgetDef('nope')).toBeUndefined();
    expect(widgetDef('metric-gauge')).toBe(WIDGET_REGISTRY['metric-gauge']);
  });

  it('unknownWidgetTypes lists distinct types not in the registry', () => {
    const widgets = [
      { type: 'metric-gauge' }, { type: 'mystery' }, { type: 'metric-card' }, { type: 'mystery' },
    ];
    expect(unknownWidgetTypes(widgets)).toEqual(['mystery']);
    expect(unknownWidgetTypes([{ type: 'metric-gauge' }])).toEqual([]);
  });
});
