import { DashboardConfig } from './models';

// Dashboard JSON file helpers (L06 / T_DB6+T_DB8): the DashboardConfig wire format is the export
// format. Download triggers a browser save; parse validates a user-supplied file shape.

/** Trigger a browser download of a dashboard as `dashboard-<id>.json`. */
export function downloadDashboard(cfg: DashboardConfig): void {
  const blob = new Blob([JSON.stringify(cfg, null, 2)], { type: 'application/json' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = `dashboard-${cfg.id || 'export'}.json`;
  a.click();
  URL.revokeObjectURL(url);
}

/** Parse + shape-check an imported dashboard JSON string. Throws on malformed input. */
export function parseDashboard(text: string): { name: string; widgets: DashboardConfig['widgets'] } {
  const data = JSON.parse(text);
  if (!data || typeof data !== 'object' || !Array.isArray(data.widgets)) {
    throw new Error('Not a dashboard file (missing widgets array).');
  }
  return { name: typeof data.name === 'string' && data.name ? data.name : 'Imported dashboard', widgets: data.widgets };
}
