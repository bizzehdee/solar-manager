import { Type } from '@angular/core';

import { DashboardData, MetricValue } from '../core/models';
import { DailyKpis } from './daily-kpis';
import { EnergyFlow } from './energy-flow';
import { HeaderWidget } from './header-widget';
import { HistoryChart } from './history-chart';
import { metricUnit } from '../core/metric-units';
import { MetricCard } from './metric-card';
import { PowerGauge } from './power-gauge';
import { StatCard } from './stat-card';
import { TimeTrendChart } from './time-trend-chart';

// Widget registry for L06 dashboards (T_DB3): maps a dashboard widget `type` → the presentational
// component plus its grid sizing rules, an editable config schema (T_DB7), and an `inputs(config,
// data)` adapter. The adapter is where config + live data become the component's specific inputs,
// so the presentational widgets stay dumb (plan.md §8) and the host stays generic.

/** One configurable field on a widget, used by the dashboard editor (T_DB7) to render a form. */
export interface WidgetConfigField {
  key: string;
  label: string;
  type: 'metric' | 'text' | 'number' | 'icon' | 'role' | 'select';
  /** Choices for `type: 'select'` (e.g. the time-series window unit). */
  options?: { value: string; label: string }[];
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
// Unit defaults to the metric's hint (e.g. `_pct`→%) unless the config overrides it.
const unitOf = (config: Record<string, unknown>, fallback = ''): string =>
  str(config['unit'], metricUnit(metricOf(config)) || fallback);

export const WIDGET_REGISTRY: Record<string, WidgetDef> = {
  header: {
    component: HeaderWidget,
    label: 'Section header',
    minW: 2,
    minH: 1,
    defaultW: 12,
    defaultH: 1,
    // A label to group/name the widgets below it; no metric, no live data.
    configSchema: [
      { key: 'text', label: 'Heading', type: 'text' },
      { key: 'icon', label: 'Icon', type: 'icon' },
      { key: 'role', label: 'Colour', type: 'role' },
    ],
    inputs: (config) => ({
      text: str(config['text'], 'Section'),
      icon: str(config['icon']),
      role: str(config['role'], 'body'),
    }),
  },
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
        unit: unitOf(config, 'W'),
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
      unit: unitOf(config),
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
      unit: unitOf(config),
      icon: str(config['icon'], 'bi-dot'),
      role: str(config['role'], 'primary'),
    }),
  },
  'time-series-chart': {
    component: TimeTrendChart,
    label: 'Time-series chart',
    minW: 4,
    minH: 4,
    defaultW: 8,
    defaultH: 6,
    // Self-fetching trend over a fixed window ("last N minutes/hours/days"); config-driven, the
    // container queries /api/history itself (so it works at any scale, not just live).
    configSchema: [
      { key: 'metric', label: 'Metric', type: 'metric' },
      { key: 'label', label: 'Label', type: 'text' },
      { key: 'unit', label: 'Unit', type: 'text' },
      { key: 'window', label: 'Show last', type: 'number' },
      {
        key: 'window_unit',
        label: 'Window unit',
        type: 'select',
        options: [
          { value: 'minutes', label: 'Minutes' },
          { value: 'hours', label: 'Hours' },
          { value: 'days', label: 'Days' },
        ],
      },
    ],
    inputs: (config) => ({ config }),
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
      {
        key: 'resolution',
        label: 'Resolution',
        type: 'select',
        options: [
          { value: 'raw', label: 'Raw samples' },
          { value: '5m', label: '5 minutes' },
          { value: '1h', label: '1 hour' },
          { value: '1d', label: '1 day' },
        ],
      },
      {
        key: 'range',
        label: 'Range',
        type: 'select',
        options: [
          { value: '1', label: 'Last 24 hours' },
          { value: '7', label: 'Last 7 days' },
          { value: '30', label: 'Last 30 days' },
        ],
      },
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
