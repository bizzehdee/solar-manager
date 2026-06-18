// Typed shapes of the backend API (plan.md §7). Mirrors the canonical metric
// vocabulary (§4) — values are mostly numeric, with a few decoded strings.

export type MetricValue = number | string | string[];

export interface DeviceSnapshot {
  ts: string;
  metrics: Record<string, MetricValue>;
}

export interface Snapshot {
  ts: string;
  devices: Record<string, DeviceSnapshot>;
}

export interface DeviceHealth {
  device_id: string;
  vendor: string;
  model: string;
  online: boolean;
  last_sample_age_s: number | null;
}

export interface Health {
  status: string;
  version: string;
  control_enabled: boolean;
  devices: DeviceHealth[];
  poll_interval_s: number;
}

export type ConnStatus = 'connecting' | 'live' | 'polling';

// History (plan.md §9). `ts` is epoch SECONDS. Rolled-up resolutions carry min/max/last/n;
// raw points carry just value. Counters (…_wh) use `last`; gauges use `value`.
export interface HistoryPoint {
  ts: number;
  value: number;
  min?: number;
  max?: number;
  last?: number;
  n?: number;
}

export interface HistoryResponse {
  device_id: string;
  metric: string;
  resolution: string;
  start: number;
  end: number;
  points: HistoryPoint[];
}

export interface HistoryMetrics {
  device_id: string;
  metrics: string[];
}

// Statistics (plan.md §10). Per-day energy accounting + derived KPIs and economics.

/** Cost/savings breakdown for a day, in the tariff currency (+ CO₂ in kg). */
export interface EconomicsResult {
  import_cost: number;
  export_revenue: number;
  net_cost: number;
  baseline_cost: number;
  savings: number;
  co2_avoided_kg: number;
}

/** Daily rollup KPIs. Ratios that may be undisclosed come back `null` (missing ≠ zero). */
export interface DailyStats {
  device_id: string;
  date: string;
  energy_wh: {
    pv: number;
    load: number;
    import: number;
    export: number;
    charge: number;
    discharge: number;
  };
  self_consumption_pct: number | null;
  self_sufficiency_pct: number | null;
  peak_pv_w: number | null;
  round_trip_efficiency: number | null; // 0..1 ratio
  economics: EconomicsResult;
  currency: string;
}

// Tariff config (plan.md §10). The backend stores full {flat, windows} rate schedules but
// PUT also accepts a bare number (treated as flat) — see ApiService.putStatsConfig.
export interface RateScheduleDict {
  flat: number;
  windows: { start_hour: number; end_hour: number; rate: number }[];
}

export interface TariffDict {
  currency: string;
  import_rate: RateScheduleDict;
  export_rate: RateScheduleDict;
  seasons: unknown[];
}

export interface StatsConfig {
  tariff: TariffDict;
  economics: Record<string, number>;
}

// Forecast (plan.md §13 / Phase 4). `ts` is epoch SECONDS throughout.

/** One forecast generation sample: expected PV power + the irradiance/temperature inputs. */
export interface GenerationPoint {
  ts: number;
  pv_w: number;
  ghi: number;
  temp_c: number;
}

/** One projected battery sample: SoC plus the power-flow components that drive it. */
export interface SocPoint {
  ts: number;
  soc_pct: number;
  pv_w: number;
  load_w: number;
  battery_w: number;
  grid_w: number;
}

/** Full forecast: expected generation curve, projected SoC, and derived projections. */
export interface DailyForecast {
  date: string; // ISO date (UTC)
  expected_wh: number; // expected PV generation that day
  min_soc_pct: number | null;
  max_soc_pct: number | null;
  battery_depleted: boolean; // projected to hit the SoC floor that day
}
export interface ForecastResponse {
  device_id: string;
  days: number; // horizon requested (1–7)
  generation: GenerationPoint[];
  soc: SocPoint[];
  daily: DailyForecast[]; // per-day summary (the multi-day report)
  depletion_ts: number | null; // epoch seconds the battery hits min SoC, or null (not projected)
  full_ts: number | null; // epoch seconds the battery hits max SoC, or null
  expected_today_wh: number;
  currency: string | null;
}

// Forecast configuration (plan.md §13 / Phase 4). Site location, PV array geometry and battery.

/** Site location + overall derating used by the PV model. */
export interface SiteSpec {
  lat: number;
  lon: number;
  performance_ratio: number;
}

/** One PV array/string. gamma_pmax/nmot default server-side (−0.26 %/°C, 41 °C) if omitted. */
export interface ArraySpec {
  name: string;
  kwp: number;
  tilt: number;
  azimuth: number;
  gamma_pmax?: number;
  nmot?: number;
}

/** Battery sizing + SoC operating window driving the projection. */
export interface BatterySpec {
  capacity_wh: number;
  min_soc_pct: number;
  max_soc_pct: number;
  max_charge_w?: number;
  max_discharge_w?: number;
}

export interface ForecastConfig {
  site: SiteSpec;
  arrays: ArraySpec[];
  battery: BatterySpec;
}

// Device registry entry (plan.md §6, §11). Returned by /api/devices CRUD.
export interface DeviceConfig {
  id: string;
  name: string;
  vendor: string;
  profile: string;
  transport: string;
  params: Record<string, unknown>;
  poll_interval: number | null;
  bms_topology: string;
  enabled: boolean;
  online: boolean;
  last_sample_age_s: number | null;
  capabilities: string[];
  control: boolean;
}
