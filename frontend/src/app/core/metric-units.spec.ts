import { metricUnit } from './metric-units';

describe('metricUnit', () => {
  it('infers the unit from the canonical key suffix', () => {
    expect(metricUnit('pv_power_w')).toBe('W');
    expect(metricUnit('today_pv_wh')).toBe('kWh');
    expect(metricUnit('grid_voltage_v')).toBe('V');
    expect(metricUnit('grid_frequency_hz')).toBe('Hz');
    expect(metricUnit('inverter_temp_c')).toBe('°C');
    expect(metricUnit('battery_soc_pct')).toBe('%');
    expect(metricUnit('self_consumption_pct')).toBe('%'); // calculated metric
    expect(metricUnit('co2_avoided_kg')).toBe('kg');
  });

  it('returns empty for keys with no obvious unit (counts, currency)', () => {
    expect(metricUnit('battery_cycles')).toBe('');
    expect(metricUnit('savings')).toBe('');
    expect(metricUnit('')).toBe('');
  });
});
