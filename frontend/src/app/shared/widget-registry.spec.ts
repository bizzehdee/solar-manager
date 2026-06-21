import { DashboardData } from '../core/models';
import { WIDGET_REGISTRY, widgetDef, unknownWidgetTypes } from './widget-registry';

const data: DashboardData = {
  metrics: { battery_soc_pct: 55, pv_power_w: 3200, grid_power_w: -1500, grid_voltage_v: 240 },
  inverterOnline: true,
};

describe('WIDGET_REGISTRY', () => {
  it('declares every L06 widget type with complete sizing metadata', () => {
    const expected = [
      'header', 'energy-flow', 'metric-gauge', 'metric-card', 'stat-card', 'time-series-chart',
      'history-chart',
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

  it('time-series-chart is config-driven (self-fetching container)', () => {
    const cfg = { metric: 'battery_soc_pct', window: 6, window_unit: 'hours' };
    const inputs = WIDGET_REGISTRY['time-series-chart'].inputs(cfg, data);
    expect(inputs['config']).toBe(cfg); // passed straight through; the widget fetches its own data
    // The window unit is a select with minutes/hours/days choices.
    const unitField = WIDGET_REGISTRY['time-series-chart'].configSchema.find((f) => f.key === 'window_unit');
    expect(unitField?.type).toBe('select');
    expect(unitField?.options?.map((o) => o.value)).toEqual(['minutes', 'hours', 'days']);
  });

  it('header defaults to a full-width 12×1 cell and passes its text through', () => {
    const def = WIDGET_REGISTRY['header'];
    expect([def.defaultW, def.defaultH]).toEqual([12, 1]);
    expect(def.inputs({ text: 'Battery' }, data)).toEqual({ text: 'Battery', icon: '', role: 'body' });
    // Empty config falls back to a generic heading (no live data needed).
    expect(def.inputs({}, data)['text']).toBe('Section');
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
