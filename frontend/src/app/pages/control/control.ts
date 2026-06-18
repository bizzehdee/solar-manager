import { Component, computed, inject, OnInit, signal } from '@angular/core';

import { ApiService } from '../../core/api.service';
import {
  DeviceConfig,
  DeviceSettingsResponse,
  SettingsField,
  SettingsSchemaResponse,
  SettingsSection,
} from '../../core/models';
import { SettingValue } from '../../shared/setting-value';

// Control — Phase 5 read-only settings display (plan.md §12 / T072). Shows the inverter's
// decoded settings (sections + fields) but does NOT write anything; schema-driven editing
// (write-back, off by default) lands in Phase 6. Values come pre-decoded from the backend
// (enum → machine int, time → "HH:MM", bool, number/int); <app-setting-value> formats them.
@Component({
  selector: 'app-control',
  imports: [SettingValue],
  template: `
    <h4 class="mb-1"><i class="bi bi-sliders"></i> Control</h4>
    <p class="small text-secondary mb-3">
      Read-only — editing inverter settings arrives in a future release.
    </p>

    <!-- Device picker: only shown when more than one device exposes settings. -->
    @if (settingsDevices().length > 1) {
      <div class="card mb-3">
        <div class="card-body py-2">
          <label class="form-label small text-secondary mb-1" for="ctrl-device">Device</label>
          <select id="ctrl-device" class="form-select" [value]="deviceId() ?? ''" (change)="onDevice($event)">
            @for (d of settingsDevices(); track d.id) {
              <option [value]="d.id">{{ d.name }}</option>
            }
          </select>
        </div>
      </div>
    }

    @if (loading()) {
      <div class="text-secondary">
        <span class="spinner-border spinner-border-sm"></span> Loading…
      </div>
    } @else if (!schema() || schema()?.supported === false) {
      <div class="alert alert-info mb-0">
        <i class="bi bi-info-circle"></i> This device exposes no settings.
      </div>
    } @else {
      @for (section of schema()!.sections; track section.key) {
        <div class="card mb-3">
          <div class="card-header">{{ section.label }}</div>
          <div class="card-body p-0">
            @if (section.repeating) {
              <!-- Repeating section (e.g. timer slots): one row per entry, one column per field. -->
              <div class="table-responsive">
                <table class="table table-sm align-middle mb-0">
                  <thead>
                    <tr>
                      <th>#</th>
                      @for (f of section.fields; track f.key) {
                        <th>{{ headerFor(f) }}</th>
                      }
                    </tr>
                  </thead>
                  <tbody>
                    @for (row of rowsFor(section); track $index) {
                      <tr>
                        <td class="text-secondary">Slot {{ $index + 1 }}</td>
                        @for (f of section.fields; track f.key) {
                          <td><app-setting-value [field]="f" [value]="row[f.key]" /></td>
                        }
                      </tr>
                    }
                  </tbody>
                </table>
              </div>
            } @else {
              <!-- Non-repeating section: a two-column label / current-value table. -->
              <table class="table table-sm align-middle mb-0">
                <tbody>
                  @for (f of section.fields; track f.key) {
                    <tr>
                      <th class="w-50 fw-normal text-secondary">{{ headerFor(f) }}</th>
                      <td class="text-end"><app-setting-value [field]="f" [value]="objFor(section)[f.key]" /></td>
                    </tr>
                  }
                </tbody>
              </table>
            }
          </div>
        </div>
      }
    }
  `,
})
export class ControlPage implements OnInit {
  private readonly api = inject(ApiService);

  /** Devices that expose a read-only settings view (drives the picker). */
  readonly devices = signal<DeviceConfig[]>([]);
  readonly settingsDevices = computed(() => this.devices().filter((d) => d.settings === true));

  readonly deviceId = signal<string | null>(null);
  readonly schema = signal<SettingsSchemaResponse | null>(null);
  readonly values = signal<DeviceSettingsResponse | null>(null);
  readonly loading = signal(false);

  ngOnInit(): void {
    this.api.getDevices().subscribe((res) => {
      this.devices.set(res.devices);
      // Prefer the first device that exposes settings; fall back to the first device.
      const withSettings = res.devices.find((d) => d.settings === true);
      const target = withSettings ?? res.devices[0];
      if (target) {
        this.deviceId.set(target.id);
        this.load(target.id);
      }
    });
  }

  onDevice(e: Event): void {
    const id = (e.target as HTMLSelectElement).value;
    this.deviceId.set(id);
    this.load(id);
  }

  /** Load the schema + current values for a device in parallel. */
  private load(id: string): void {
    this.loading.set(true);
    let pending = 2;
    const done = () => {
      if (--pending === 0) this.loading.set(false);
    };
    this.api.getDeviceSettingsSchema(id).subscribe({
      next: (s) => {
        this.schema.set(s);
        done();
      },
      error: () => {
        this.schema.set(null);
        done();
      },
    });
    this.api.getDeviceSettings(id).subscribe({
      next: (v) => {
        this.values.set(v);
        done();
      },
      error: () => {
        this.values.set(null);
        done();
      },
    });
  }

  /** Decoded values for a non-repeating section (object), or {} when absent. */
  objFor(section: SettingsSection): Record<string, unknown> {
    const v = this.values()?.values?.[section.key];
    return (v && typeof v === 'object' && !Array.isArray(v) ? v : {}) as Record<string, unknown>;
  }

  /** Decoded value rows for a repeating section (array), or [] when absent. */
  rowsFor(section: SettingsSection): Record<string, unknown>[] {
    const v = this.values()?.values?.[section.key];
    return (Array.isArray(v) ? v : []) as Record<string, unknown>[];
  }

  /** Column/row header: the field label with its unit appended when present. */
  headerFor(f: SettingsField): string {
    return f.unit ? `${f.label} (${f.unit})` : f.label;
  }
}
