import { Type } from '@angular/core';

import { DashboardData, MetricValue } from '../core/models';
import { ChartWidget } from './chart-widget';
import { EnergyFlow } from './energy-flow';
import { HeaderWidget } from './header-widget';
import { metricUnit } from '../core/metric-units';
import { MetricCard } from './metric-card';
import { PowerGauge } from './power-gauge';

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
  // Card: renders whatever the metric returns — numbers are decimal-formatted, strings shown as-is,
  // missing → em-dash. The value is passed straight through (not coerced to a number) so text metrics
  // render. Merged from the old metric-card + stat-card (the latter is a back-compat alias below).
  'metric-card': {
    component: MetricCard,
    label: 'Card',
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
      value: data.metrics[metricOf(config)] ?? undefined,
      unit: unitOf(config),
      icon: str(config['icon'], 'bi-dot'),
      role: str(config['role'], 'primary'),
    }),
  },
  // Self-contained container widget: it fetches its own /api/history data, so the `inputs` adapter
  // only passes config through. Window = value + unit ("last N minutes/hours/days"); resolution is
  // auto-derived from the window unless pinned.
  chart: {
    component: ChartWidget,
    label: 'Chart',
    minW: 4,
    minH: 4,
    defaultW: 8,
    defaultH: 6,
    configSchema: [
      { key: 'metric', label: 'Metric', type: 'metric' },
      { key: 'label', label: 'Header', type: 'text' },
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
      {
        key: 'resolution',
        label: 'Resolution',
        type: 'select',
        options: [
          { value: 'auto', label: 'Auto' },
          { value: 'raw', label: 'Raw samples' },
          { value: '5m', label: '5 minutes' },
          { value: '1h', label: '1 hour' },
          { value: '1d', label: '1 day' },
        ],
      },
    ],
    inputs: (config) => ({ config }),
  },
};

// Back-compat: the chart was split into `time-series-chart` + `history-chart` before they were
// merged into `chart`. Old stored dashboards still reference those types, so resolve them to `chart`
// (the unified ChartWidget reads both config shapes). Aliases aren't in WIDGET_REGISTRY, so the
// "Add widget" menu shows a single "Chart" entry.
const WIDGET_ALIASES: Record<string, string> = {
  'time-series-chart': 'chart',
  'history-chart': 'chart',
  // stat-card was merged into metric-card (one card that renders numbers or text).
  'stat-card': 'metric-card',
};

export function widgetDef(type: string): WidgetDef | undefined {
  return WIDGET_REGISTRY[type] ?? WIDGET_REGISTRY[WIDGET_ALIASES[type]];
}

/** Distinct widget types in `widgets` that aren't in the registry (for import validation —
 *  unknown types are a warning, not a hard error: they render an "Unknown widget" placeholder). */
export function unknownWidgetTypes(widgets: { type: string }[]): string[] {
  return [...new Set(widgets.filter((w) => !widgetDef(w.type)).map((w) => w.type))];
}
