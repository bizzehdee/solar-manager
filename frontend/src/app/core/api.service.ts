import { Injectable, inject } from '@angular/core';
import { HttpClient, HttpParams } from '@angular/common/http';
import { Observable } from 'rxjs';

import {
  DailyStats,
  DeviceConfig,
  ForecastConfig,
  ForecastResponse,
  Health,
  HistoryMetrics,
  HistoryResponse,
  Snapshot,
  StatsConfig,
} from './models';

// REST surface (plan.md §7). Same-origin in production; proxied to the backend in dev.
@Injectable({ providedIn: 'root' })
export class ApiService {
  private http = inject(HttpClient);

  getHealth(): Observable<Health> {
    return this.http.get<Health>('/api/health');
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

  /** Expected generation + projected SoC for a device (omit ⇒ first/only device). */
  getForecast(deviceId?: string): Observable<ForecastResponse> {
    let params = new HttpParams();
    if (deviceId !== undefined) params = params.set('device_id', deviceId);
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
