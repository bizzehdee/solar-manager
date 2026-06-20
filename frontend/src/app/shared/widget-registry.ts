import { Type } from '@angular/core';

import { DashboardData, MetricValue } from '../core/models';
import { DailyKpis } from './daily-kpis';
import { EnergyFlow } from './energy-flow';
import { HistoryChart } from './history-chart';
import { MetricCard } from './metric-card';
import { PowerGauge } from './power-gauge';
import { StatCard } from './stat-card';
import { TimeSeriesChart } from './time-series-chart';

// Widget registry for L06 dashboards (T_DB3): maps a dashboard widget `type` → the presentational
// component plus its grid sizing rules, an editable config schema (T_DB7), and an `inputs(config,
// data)` adapter. The adapter is where config + live data become the component's specific inputs,
// so the presentational widgets stay dumb (plan.md §8) and the host stays generic.

/** One configurable field on a widget, used by the dashboard editor (T_DB7) to render a form. */
export interface WidgetConfigField {
  key: string;
  label: string;
  type: 'metric' | 'text' | 'number' | 'icon' | 'role';
}

export interface WidgetDef {
  component: Type<unknown>;
  label: string;
  minW: number;
  minH: number;
  defaultW: number;
  defaultH: number;
  configSchema: WidgetConfigField[];
  /** Map the widget's stored config + the dashboard's live data to the component's input bag. */
  inputs: (config: Record<string, unknown>, data: DashboardData) => Record<string, unknown>;
}

const num = (v: MetricValue | undefined): number | undefined => (typeof v === 'number' ? v : undefined);
const str = (v: unknown, fallback = ''): string => (typeof v === 'string' && v ? v : fallback);
const metricOf = (config: Record<string, unknown>, fallback = ''): string => str(config['metric'], fallback);

export const WIDGET_REGISTRY: Record<string, WidgetDef> = {
  'energy-flow': {
    component: EnergyFlow,
    label: 'Energy flow',
    minW: 4,
    minH: 4,
    defaultW: 6,
    defaultH: 6,
    configSchema: [],
    inputs: (_config, data) => ({ metrics: data.metrics, inverterOnline: data.inverterOnline ?? true }),
  },
  'metric-gauge': {
    component: PowerGauge,
    label: 'Metric gauge',
    minW: 2,
    minH: 2,
    defaultW: 2,
    defaultH: 2,
    // Generic radial gauge: pick any metric and (optionally) override its name, unit, full-scale
    // and colour — e.g. battery_soc_pct with unit "%" and full-scale 100.
    configSchema: [
      { key: 'metric', label: 'Metric', type: 'metric' },
      { key: 'label', label: 'Name', type: 'text' },
      { key: 'unit', label: 'Unit', type: 'text' },
      { key: 'max', label: 'Full-scale', type: 'number' },
      { key: 'role', label: 'Colour', type: 'role' },
    ],
    // The gauge shows the magnitude (bidirectional flows pass abs; plan.md §4 signs not re-derived).
    inputs: (config, data) => {
      const v = num(data.metrics[metricOf(config)]);
      return {
        value: v === undefined ? 0 : Math.abs(v),
        max: num(config['max'] as MetricValue) ?? 8000,
        label: str(config['label'], metricOf(config)),
        unit: str(config['unit'], 'W'),
        role: str(config['role'], 'primary'),
      };
    },
  },
  'metric-card': {
    component: MetricCard,
    label: 'Metric card',
    minW: 2,
    minH: 1,
    defaultW: 2,
    defaultH: 1,
    configSchema: [
      { key: 'metric', label: 'Metric', type: 'metric' },
      { key: 'label', label: 'Label', type: 'text' },
      { key: 'unit', label: 'Unit', type: 'text' },
      { key: 'icon', label: 'Icon', type: 'icon' },
      { key: 'role', label: 'Colour', type: 'role' },
    ],
    inputs: (config, data) => ({
      label: str(config['label'], metricOf(config)),
      value: num(data.metrics[metricOf(config)]),
      unit: str(config['unit']),
      icon: str(config['icon'], 'bi-dot'),
      role: str(config['role'], 'primary'),
    }),
  },
  'stat-card': {
    component: StatCard,
    label: 'Stat card',
    minW: 2,
    minH: 2,
    defaultW: 4,
    defaultH: 2,
    configSchema: [
      { key: 'metric', label: 'Metric', type: 'metric' },
      { key: 'label', label: 'Label', type: 'text' },
      { key: 'unit', label: 'Unit', type: 'text' },
      { key: 'icon', label: 'Icon', type: 'icon' },
      { key: 'role', label: 'Colour', type: 'role' },
    ],
    inputs: (config, data) => ({
      label: str(config['label'], metricOf(config)),
      value: data.metrics[metricOf(config)] ?? undefined,
      unit: str(config['unit']),
      icon: str(config['icon'], 'bi-dot'),
      role: str(config['role'], 'primary'),
    }),
  },
  'time-series-chart': {
    component: TimeSeriesChart,
    label: 'Time-series chart',
    minW: 4,
    minH: 4,
    defaultW: 8,
    defaultH: 6,
    configSchema: [
      { key: 'metric', label: 'Metric', type: 'metric' },
      { key: 'label', label: 'Label', type: 'text' },
      { key: 'unit', label: 'Unit', type: 'text' },
    ],
    // History is supplied by the host via `data.series[metric]`; absent ⇒ an empty chart.
    inputs: (config, data) => ({
      points: data.series?.[metricOf(config)] ?? [],
      label: str(config['label'], metricOf(config)),
      unit: str(config['unit']),
    }),
  },
  // Container widgets for the History dashboard (T_DB5): self-contained (fetch their own data),
  // so their `inputs` adapters only pass config — the host provides no live data to them.
  'daily-kpis': {
    component: DailyKpis,
    label: 'Daily KPIs',
    minW: 6,
    minH: 2,
    defaultW: 12,
    defaultH: 2,
    configSchema: [],
    inputs: () => ({}),
  },
  'history-chart': {
    component: HistoryChart,
    label: 'History chart',
    minW: 6,
    minH: 4,
    defaultW: 12,
    defaultH: 6,
    configSchema: [
      { key: 'metric', label: 'Metric', type: 'metric' },
      { key: 'resolution', label: 'Resolution', type: 'text' },
      { key: 'range', label: 'Range (days)', type: 'number' },
    ],
    inputs: (config) => ({ config }),
  },
};

export function widgetDef(type: string): WidgetDef | undefined {
  return WIDGET_REGISTRY[type];
}

/** Distinct widget types in `widgets` that aren't in the registry (for import validation —
 *  unknown types are a warning, not a hard error: they render an "Unknown widget" placeholder). */
export function unknownWidgetTypes(widgets: { type: string }[]): string[] {
  return [...new Set(widgets.filter((w) => !(w.type in WIDGET_REGISTRY)).map((w) => w.type))];
}
