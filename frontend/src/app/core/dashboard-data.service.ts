import { Injectable, computed, inject } from '@angular/core';

import { LiveService } from './live.service';
import { DashboardData, MetricValue } from './models';

// Live data source for dashboards (L06 / T_DB4). Derives a `DashboardData` bag from the WebSocket
// snapshot (LiveService) so the dashboard host can feed every widget without each page re-deriving
// it. The socket itself is started once by the app shell; this service only reads it.
@Injectable({ providedIn: 'root' })
export class DashboardDataService {
  private readonly live = inject(LiveService);

  /** Metrics of the first device in the live snapshot (single-inverter rig in Phase 0). */
  readonly metrics = computed<Record<string, MetricValue> | null>(() => {
    const snap = this.live.snapshot();
    if (!snap) return null;
    return Object.values(snap.devices)[0]?.metrics ?? null;
  });

  /** Active fault codes (string[]) — empty when absent/healthy. */
  readonly faultCodes = computed<string[]>(() => {
    const v = this.metrics()?.['inverter_fault_codes'];
    return Array.isArray(v) ? v : [];
  });

  /** Decoded run-state string, if reported. */
  readonly runState = computed<string | undefined>(() => {
    const v = this.metrics()?.['run_state'];
    return typeof v === 'string' ? v : undefined;
  });

  /** Inverter online (energy-flow centre ring): a live reading, no active faults, and not in a
   *  fault/standby/shutdown run-state. */
  readonly inverterOnline = computed<boolean>(() => {
    if (!this.metrics()) return false;
    if (this.faultCodes().length > 0) return false;
    const rs = this.runState()?.toLowerCase();
    return rs !== 'fault' && rs !== 'standby' && rs !== 'shutdown';
  });

  /** The bag the dashboard host hands to each widget's `inputs(config, data)` adapter. */
  readonly data = computed<DashboardData>(() => ({
    metrics: this.metrics() ?? {},
    inverterOnline: this.inverterOnline(),
  }));
}
