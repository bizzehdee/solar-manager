import { Injectable, inject } from '@angular/core';
import { HttpClient, HttpParams } from '@angular/common/http';
import { Observable } from 'rxjs';

import {
  Alert,
  AlertsResponse,
  AuditEntry,
  DailyStats,
  DeviceClock,
  Diagnostics,
  DeviceConfig,
  DeviceSettingsResponse,
  ForecastConfig,
  ForecastResponse,
  Health,
  HistoryMetrics,
  HistoryResponse,
  SettingsSchemaResponse,
  Snapshot,
  StatsConfig,
  WriteSettingsResponse,
} from './models';

// REST surface (plan.md §7). Same-origin in production; proxied to the backend in dev.
@Injectable({ providedIn: 'root' })
export class ApiService {
  private http = inject(HttpClient);

  getHealth(): Observable<Health> {
    return this.http.get<Health>('/api/health');
  }

  /** Operational diagnostics (build/schema, DB size, rollup lag, per-device comms). */
  getDiagnostics(): Observable<Diagnostics> {
    return this.http.get<Diagnostics>('/api/diagnostics');
  }

  getLive(): Observable<Snapshot> {
    return this.http.get<Snapshot>('/api/live');
  }

  // --- History (plan.md §9) ---

  /** Available metric keys for charting; optionally scoped to one device. */
  getHistoryMetrics(deviceId?: string): Observable<HistoryMetrics> {
    let params = new HttpParams();
    if (deviceId !== undefined) params = params.set('device_id', deviceId);
    return this.http.get<HistoryMetrics>('/api/history/metrics', { params });
  }

  /** Time-series for one metric. start/end accept epoch seconds or ISO; omit ⇒ last 24h. */
  getHistory(p: {
    metric: string;
    deviceId?: string;
    start?: string | number;
    end?: string | number;
    resolution?: string;
  }): Observable<HistoryResponse> {
    let params = new HttpParams().set('metric', p.metric);
    if (p.deviceId !== undefined) params = params.set('device_id', p.deviceId);
    if (p.start !== undefined) params = params.set('start', String(p.start));
    if (p.end !== undefined) params = params.set('end', String(p.end));
    if (p.resolution !== undefined) params = params.set('resolution', p.resolution);
    return this.http.get<HistoryResponse>('/api/history', { params });
  }

  // --- Devices (plan.md §6, §11) ---

  getDevices(): Observable<{ devices: DeviceConfig[] }> {
    return this.http.get<{ devices: DeviceConfig[] }>('/api/devices');
  }

  createDevice(body: Record<string, unknown>): Observable<DeviceConfig> {
    return this.http.post<DeviceConfig>('/api/devices', body);
  }

  updateDevice(id: string, body: Record<string, unknown>): Observable<DeviceConfig> {
    return this.http.put<DeviceConfig>(`/api/devices/${id}`, body);
  }

  deleteDevice(id: string): Observable<void> {
    return this.http.delete<void>(`/api/devices/${id}`);
  }

  // --- Settings display (plan.md §12 / Phase 5, read-only) ---

  /** Settings schema (sections + fields) for a device's read-only settings view. */
  getDeviceSettingsSchema(deviceId: string): Observable<SettingsSchemaResponse> {
    return this.http.get<SettingsSchemaResponse>(`/api/devices/${deviceId}/settings/schema`);
  }

  /** Decoded current settings values for a device (keyed by section). */
  getDeviceSettings(deviceId: string): Observable<DeviceSettingsResponse> {
    return this.http.get<DeviceSettingsResponse>(`/api/devices/${deviceId}/settings`);
  }

  // --- Settings write-back (plan.md §12 / Phase 6; gated by SOLARVOLT_ENABLE_CONTROL) ---

  /** Write one section (or one timer slot via `index`) of settings. `etag` is sent as
   *  If-Match for optimistic concurrency (412 if the device changed since it was read). */
  putDeviceSettings(
    deviceId: string,
    body: { section: string; index?: number | null; values: Record<string, unknown> },
    etag?: string | null,
  ): Observable<WriteSettingsResponse> {
    const headers = etag ? { 'If-Match': etag } : undefined;
    return this.http.put<WriteSettingsResponse>(`/api/devices/${deviceId}/settings`, body, { headers });
  }

  /** Recent settings-write audit entries (most recent first), optionally for one device. */
  getAudit(deviceId?: string, limit = 20): Observable<{ entries: AuditEntry[] }> {
    let params = new HttpParams().set('limit', String(limit));
    if (deviceId !== undefined) params = params.set('device_id', deviceId);
    return this.http.get<{ entries: AuditEntry[] }>('/api/audit', { params });
  }

  // --- Alerts (plan.md §15) ---

  /** Alerts inbox: active-only or full history, with the active-unacked count for the bell. */
  getAlerts(active = false, limit = 100): Observable<AlertsResponse> {
    const params = new HttpParams().set('active', String(active)).set('limit', String(limit));
    return this.http.get<AlertsResponse>('/api/alerts', { params });
  }

  ackAlert(id: number): Observable<unknown> {
    return this.http.post(`/api/alerts/${id}/ack`, {});
  }

  snoozeAlert(id: number, minutes = 60): Observable<unknown> {
    return this.http.post(`/api/alerts/${id}/snooze`, { minutes });
  }

  // --- Inverter clock (plan.md §19 / T097) ---

  getDeviceClock(deviceId: string): Observable<DeviceClock> {
    return this.http.get<DeviceClock>(`/api/devices/${deviceId}/clock`);
  }

  /** Correct the inverter clock to system time (403 unless control is enabled + syncable). */
  syncDeviceClock(deviceId: string): Observable<unknown> {
    return this.http.post(`/api/devices/${deviceId}/clock/sync`, {});
  }

  // --- Statistics (plan.md §10) ---

  /** Daily KPIs/economics. `date` accepts an ISO date or epoch seconds; omit ⇒ today. */
  getDailyStats(deviceId?: string, date?: string): Observable<DailyStats> {
    let params = new HttpParams();
    if (deviceId !== undefined) params = params.set('device_id', deviceId);
    if (date !== undefined) params = params.set('date', date);
    return this.http.get<DailyStats>('/api/stats/daily', { params });
  }

  /** Tariff + economics configuration backing the savings calculations. */
  getStatsConfig(): Observable<StatsConfig> {
    return this.http.get<StatsConfig>('/api/stats/config');
  }

  /** Update tariff/economics. `import_rate`/`export_rate` accept a bare number (flat). */
  putStatsConfig(body: { tariff?: unknown; economics?: Record<string, number> }): Observable<StatsConfig> {
    return this.http.put<StatsConfig>('/api/stats/config', body);
  }

  // --- Forecast (plan.md §13 / Phase 4) ---

  /** Expected generation + projected SoC for a device over `days` (1–7) days
   *  (omit deviceId ⇒ first/only device). */
  getForecast(deviceId?: string, days?: number): Observable<ForecastResponse> {
    let params = new HttpParams();
    if (deviceId !== undefined) params = params.set('device_id', deviceId);
    if (days !== undefined) params = params.set('days', String(days));
    return this.http.get<ForecastResponse>('/api/forecast', { params });
  }

  /** Site/array/battery configuration backing the forecast model. */
  getForecastConfig(): Observable<ForecastConfig> {
    return this.http.get<ForecastConfig>('/api/forecast/config');
  }

  /** Update forecast config (partial). Returns the full, merged config. */
  putForecastConfig(body: Partial<ForecastConfig>): Observable<ForecastConfig> {
    return this.http.put<ForecastConfig>('/api/forecast/config', body);
  }
}
