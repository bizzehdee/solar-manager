import { parseDashboard } from './dashboard-file';

describe('parseDashboard', () => {
  it('parses a valid dashboard JSON', () => {
    const text = JSON.stringify({
      id: 'now', name: 'My Now', builtin: true,
      widgets: [{ type: 'metric-gauge', x: 0, y: 0, w: 2, h: 2, config: { metric: 'pv_power_w' } }],
    });
    const out = parseDashboard(text);
    expect(out.name).toBe('My Now');
    expect(out.widgets.length).toBe(1);
  });

  it('defaults a missing name', () => {
    expect(parseDashboard(JSON.stringify({ widgets: [] })).name).toBe('Imported dashboard');
  });

  it('throws on non-JSON', () => {
    expect(() => parseDashboard('not json')).toThrow();
  });

  it('throws when widgets is missing or not an array', () => {
    expect(() => parseDashboard(JSON.stringify({ name: 'X' }))).toThrow();
    expect(() => parseDashboard(JSON.stringify({ name: 'X', widgets: 'no' }))).toThrow();
  });
});
