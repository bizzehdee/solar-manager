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
