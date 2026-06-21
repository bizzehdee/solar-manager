// Default unit hint for a metric key, inferred from the canonical suffix convention (plan.md §4).
// Used to pre-fill / suggest the unit on dashboard cards so a metric carries a sensible unit
// without the user typing one — for live metrics (pv_power_w → "W") and calculated ones
// (self_consumption_pct → "%") alike. Returns '' when there's no obvious unit (e.g. counts,
// currency — which the user sets explicitly).
export function metricUnit(key: string): string {
  if (key.endsWith('_wh')) return 'kWh'; // counters render as kWh
  if (key.endsWith('_w')) return 'W';
  if (key.endsWith('_va')) return 'VA';
  if (key.endsWith('_v')) return 'V';
  if (key.endsWith('_a')) return 'A';
  if (key.endsWith('_hz')) return 'Hz';
  if (key.endsWith('_c')) return '°C';
  if (key.endsWith('_pct')) return '%';
  if (key.endsWith('_kg')) return 'kg';
  return '';
}
