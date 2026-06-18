import { Component, inject, OnInit, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';

import { ApiService } from '../../core/api.service';
import { ArraySpec, DeviceConfig, ForecastConfig, StatsConfig } from '../../core/models';

// Settings › Devices (plan.md §6, §11): the device registry. Lists configured devices and
// offers an inline add/edit/delete form. Single-house deployment, no auth (CLAUDE.md).
@Component({
  selector: 'app-settings',
  imports: [FormsModule],
  template: `
    <h4 class="mb-3"><i class="bi bi-gear"></i> Settings — Devices</h4>

    <div class="card mb-3">
      <div class="card-header">Configured devices</div>
      <div class="card-body p-0">
        @if (devices().length === 0) {
          <div class="alert alert-secondary m-3 mb-0">No devices configured yet.</div>
        } @else {
          <div class="table-responsive">
            <table class="table align-middle mb-0">
              <thead>
                <tr>
                  <th>Name</th>
                  <th>Vendor / Profile</th>
                  <th>Transport</th>
                  <th>Status</th>
                  <th>Capabilities</th>
                  <th>Enabled</th>
                  <th class="text-end">Actions</th>
                </tr>
              </thead>
              <tbody>
                @for (d of devices(); track d.id) {
                  <tr>
                    <td>
                      <div class="fw-semibold">{{ d.name }}</div>
                      <div class="small text-secondary">{{ d.id }}</div>
                    </td>
                    <td>{{ d.vendor }} / {{ d.profile }}</td>
                    <td>{{ d.transport }}</td>
                    <td>
                      <span class="badge" [class]="d.online ? 'text-bg-success' : 'text-bg-danger'">
                        {{ d.online ? 'online' : 'offline' }}
                      </span>
                    </td>
                    <td>{{ d.capabilities.length }}</td>
                    <td>
                      <div class="form-check form-switch mb-0">
                        <input
                          class="form-check-input"
                          type="checkbox"
                          [checked]="d.enabled"
                          (change)="toggleEnabled(d, $event)"
                          [attr.aria-label]="'Enable ' + d.name"
                        />
                      </div>
                    </td>
                    <td class="text-end text-nowrap">
                      <button class="btn btn-sm btn-outline-secondary me-1" (click)="startRename(d)">
                        <i class="bi bi-pencil"></i>
                      </button>
                      <button class="btn btn-sm btn-outline-danger" (click)="remove(d)">
                        <i class="bi bi-trash"></i>
                      </button>
                    </td>
                  </tr>
                  @if (renameId() === d.id) {
                    <tr>
                      <td colspan="7">
                        <div class="input-group input-group-sm">
                          <span class="input-group-text">New name</span>
                          <input class="form-control" [(ngModel)]="renameValue" name="rename" />
                          <button class="btn btn-primary" (click)="saveRename(d)">Save</button>
                          <button class="btn btn-outline-secondary" (click)="renameId.set(null)">Cancel</button>
                        </div>
                      </td>
                    </tr>
                  }
                }
              </tbody>
            </table>
          </div>
        }
      </div>
    </div>

    <div class="card">
      <div class="card-header">Add device</div>
      <div class="card-body">
        @if (error()) {
          <div class="alert alert-danger">{{ error() }}</div>
        }
        <form (ngSubmit)="add()">
          <div class="row g-3">
            <div class="col-12 col-md-4">
              <label class="form-label small text-secondary" for="dev-id">ID</label>
              <input id="dev-id" class="form-control" [(ngModel)]="form.id" name="id" required />
            </div>
            <div class="col-12 col-md-4">
              <label class="form-label small text-secondary" for="dev-name">Name</label>
              <input id="dev-name" class="form-control" [(ngModel)]="form.name" name="name" />
            </div>
            <div class="col-12 col-md-4">
              <label class="form-label small text-secondary" for="dev-transport">Transport</label>
              <select id="dev-transport" class="form-select" [(ngModel)]="form.transport" name="transport">
                <option value="dummy">dummy</option>
                <option value="modbus_rtu">modbus_rtu</option>
              </select>
            </div>
            @if (form.transport === 'modbus_rtu') {
              <div class="col-12 col-md-4">
                <label class="form-label small text-secondary" for="dev-profile">Profile</label>
                <input id="dev-profile" class="form-control" [(ngModel)]="form.profile" name="profile" />
              </div>
              <div class="col-12 col-md-4">
                <label class="form-label small text-secondary" for="dev-port">Serial port</label>
                <input id="dev-port" class="form-control" [(ngModel)]="form.port" name="port" placeholder="/dev/ttyUSB0" />
              </div>
              <div class="col-12 col-md-4">
                <label class="form-label small text-secondary" for="dev-slave">Slave ID</label>
                <input id="dev-slave" type="number" class="form-control" [(ngModel)]="form.slaveId" name="slaveId" />
              </div>
            }
          </div>
          <div class="mt-3">
            <button type="submit" class="btn btn-primary" [disabled]="!form.id">
              <i class="bi bi-plus-lg"></i> Add device
            </button>
          </div>
        </form>
      </div>
    </div>

    <!-- Tariff & economics (T051/T052): flat rates + currency + CO₂ intensity. The backend
         accepts a bare number for import_rate/export_rate (treated as flat) — no TOU editor needed. -->
    <div class="card mt-3">
      <div class="card-header"><i class="bi bi-cash-coin"></i> Tariff &amp; economics</div>
      <div class="card-body">
        @if (tariffSaved()) {
          <div class="alert alert-success">Saved — economics refreshed.</div>
        }
        <form (ngSubmit)="saveTariff()">
          <div class="row g-3">
            <div class="col-6 col-md-3">
              <label class="form-label small text-secondary" for="t-currency">Currency</label>
              <input id="t-currency" class="form-control" [(ngModel)]="tariff.currency" name="currency" />
            </div>
            <div class="col-6 col-md-3">
              <label class="form-label small text-secondary" for="t-import">Import rate (/kWh)</label>
              <input id="t-import" type="number" step="any" class="form-control" [(ngModel)]="tariff.importRate" name="importRate" />
            </div>
            <div class="col-6 col-md-3">
              <label class="form-label small text-secondary" for="t-export">Export rate (/kWh)</label>
              <input id="t-export" type="number" step="any" class="form-control" [(ngModel)]="tariff.exportRate" name="exportRate" />
            </div>
            <div class="col-6 col-md-3">
              <label class="form-label small text-secondary" for="t-co2">CO₂ intensity (g/kWh)</label>
              <input id="t-co2" type="number" step="any" class="form-control" [(ngModel)]="tariff.co2Intensity" name="co2Intensity" />
            </div>
            <div class="col-6 col-md-3">
              <label class="form-label small text-secondary" for="t-cost">System cost</label>
              <input id="t-cost" type="number" step="any" class="form-control" [(ngModel)]="tariff.systemCost" name="systemCost" />
            </div>
          </div>
          <div class="mt-3">
            <button type="submit" class="btn btn-primary"><i class="bi bi-save"></i> Save tariff</button>
          </div>
        </form>
      </div>
    </div>

    <!-- Solar array & site (T064): drives the Phase 4 forecast model. Site location + overall
         derating, the PV array geometry (one row per string), and the battery operating window. -->
    <div class="card mt-3">
      <div class="card-header"><i class="bi bi-sun"></i> Solar array &amp; site</div>
      <div class="card-body">
        @if (forecastSaved()) {
          <div class="alert alert-success">Saved — forecast updated.</div>
        }
        <form (ngSubmit)="saveForecast()">
          <h6 class="text-secondary">Site</h6>
          <div class="row g-3 mb-3">
            <div class="col-6 col-md-4">
              <label class="form-label small text-secondary" for="f-lat">Latitude</label>
              <input id="f-lat" type="number" step="any" class="form-control" [(ngModel)]="forecast.site.lat" name="lat" />
            </div>
            <div class="col-6 col-md-4">
              <label class="form-label small text-secondary" for="f-lon">Longitude</label>
              <input id="f-lon" type="number" step="any" class="form-control" [(ngModel)]="forecast.site.lon" name="lon" />
            </div>
            <div class="col-6 col-md-4">
              <label class="form-label small text-secondary" for="f-pr">Performance ratio</label>
              <input id="f-pr" type="number" step="any" class="form-control" [(ngModel)]="forecast.site.performance_ratio" name="pr" />
            </div>
          </div>

          <h6 class="text-secondary">Battery</h6>
          <div class="row g-3 mb-3">
            <div class="col-6 col-md-4">
              <label class="form-label small text-secondary" for="f-cap">Capacity (Wh)</label>
              <input id="f-cap" type="number" step="any" class="form-control" [(ngModel)]="forecast.battery.capacity_wh" name="capacityWh" />
            </div>
            <div class="col-6 col-md-4">
              <label class="form-label small text-secondary" for="f-min">Min SoC (%)</label>
              <input id="f-min" type="number" step="any" class="form-control" [(ngModel)]="forecast.battery.min_soc_pct" name="minSoc" />
            </div>
            <div class="col-6 col-md-4">
              <label class="form-label small text-secondary" for="f-max">Max SoC (%)</label>
              <input id="f-max" type="number" step="any" class="form-control" [(ngModel)]="forecast.battery.max_soc_pct" name="maxSoc" />
            </div>
          </div>

          <h6 class="text-secondary">Array segments</h6>
          <p class="small text-secondary">
            Temperature coefficient and NOCT default to −0.26 %/°C and 41 °C when left blank.
          </p>
          @if (forecast.arrays.length === 0) {
            <div class="alert alert-secondary">No array segments — add one below.</div>
          }
          @for (seg of forecast.arrays; track $index) {
            <div class="row g-2 mb-2 align-items-end">
              <div class="col-6 col-md-3">
                <label class="form-label small text-secondary" [attr.for]="'seg-name-' + $index">Name</label>
                <input [id]="'seg-name-' + $index" class="form-control" [(ngModel)]="seg.name" [name]="'segName' + $index" />
              </div>
              <div class="col-6 col-md-2">
                <label class="form-label small text-secondary" [attr.for]="'seg-kwp-' + $index">kWp</label>
                <input [id]="'seg-kwp-' + $index" type="number" step="any" class="form-control" [(ngModel)]="seg.kwp" [name]="'segKwp' + $index" />
              </div>
              <div class="col-6 col-md-2">
                <label class="form-label small text-secondary" [attr.for]="'seg-tilt-' + $index">Tilt (°)</label>
                <input [id]="'seg-tilt-' + $index" type="number" step="any" class="form-control" [(ngModel)]="seg.tilt" [name]="'segTilt' + $index" />
              </div>
              <div class="col-6 col-md-2">
                <label class="form-label small text-secondary" [attr.for]="'seg-az-' + $index">Azimuth (°)</label>
                <input [id]="'seg-az-' + $index" type="number" step="any" class="form-control" [(ngModel)]="seg.azimuth" [name]="'segAz' + $index" />
              </div>
              <div class="col-12 col-md-3">
                <button type="button" class="btn btn-outline-danger" (click)="removeSegment($index)">
                  <i class="bi bi-trash"></i> Remove
                </button>
              </div>
            </div>
          }
          <div class="mt-2 mb-3">
            <button type="button" class="btn btn-outline-secondary" (click)="addSegment()">
              <i class="bi bi-plus-lg"></i> Add segment
            </button>
          </div>

          <button type="submit" class="btn btn-primary"><i class="bi bi-save"></i> Save forecast config</button>
        </form>
      </div>
    </div>
  `,
})
export class SettingsPage implements OnInit {
  private readonly api = inject(ApiService);

  readonly devices = signal<DeviceConfig[]>([]);
  readonly error = signal<string | null>(null);
  readonly renameId = signal<string | null>(null);
  renameValue = '';

  form = {
    id: '',
    name: '',
    transport: 'dummy',
    profile: '',
    port: '',
    slaveId: 1,
  };

  // Tariff form (T051/T052) — flat rates only; the backend treats bare numbers as flat.
  readonly tariffSaved = signal(false);
  tariff = {
    currency: 'GBP',
    importRate: 0,
    exportRate: 0,
    co2Intensity: 0,
    systemCost: 0,
  };

  // Forecast config form (T064) — site/array/battery driving the Phase 4 forecast.
  readonly forecastSaved = signal(false);
  forecast: ForecastConfig = {
    site: { lat: 0, lon: 0, performance_ratio: 0.85 },
    arrays: [],
    battery: { capacity_wh: 0, min_soc_pct: 0, max_soc_pct: 100 },
  };

  ngOnInit(): void {
    this.refresh();
    this.loadTariff();
    this.loadForecast();
  }

  private loadForecast(): void {
    this.api.getForecastConfig().subscribe((cfg) => (this.forecast = cfg));
  }

  /** Append a blank array segment row (gamma_pmax/nmot default server-side). */
  addSegment(): void {
    const seg: ArraySpec = { name: '', kwp: 0, tilt: 30, azimuth: 180 };
    this.forecast = { ...this.forecast, arrays: [...this.forecast.arrays, seg] };
  }

  /** Drop the array segment at `index`. */
  removeSegment(index: number): void {
    this.forecast = {
      ...this.forecast,
      arrays: this.forecast.arrays.filter((_, i) => i !== index),
    };
  }

  saveForecast(): void {
    this.forecastSaved.set(false);
    this.api
      .putForecastConfig({
        site: this.forecast.site,
        arrays: this.forecast.arrays,
        battery: this.forecast.battery,
      })
      .subscribe((cfg) => {
        this.forecast = cfg;
        this.forecastSaved.set(true);
      });
  }

  private loadTariff(): void {
    this.api.getStatsConfig().subscribe((cfg) => this.applyStatsConfig(cfg));
  }

  /** Map the API config into the flat-rate form fields. */
  private applyStatsConfig(cfg: StatsConfig): void {
    this.tariff = {
      currency: cfg.tariff.currency,
      importRate: cfg.tariff.import_rate?.flat ?? 0,
      exportRate: cfg.tariff.export_rate?.flat ?? 0,
      co2Intensity: cfg.economics?.['co2_intensity_g_per_kwh'] ?? 0,
      systemCost: cfg.economics?.['system_cost'] ?? 0,
    };
  }

  saveTariff(): void {
    this.tariffSaved.set(false);
    this.api
      .putStatsConfig({
        tariff: {
          import_rate: Number(this.tariff.importRate),
          export_rate: Number(this.tariff.exportRate),
          currency: this.tariff.currency,
        },
        economics: {
          co2_intensity_g_per_kwh: Number(this.tariff.co2Intensity),
          system_cost: Number(this.tariff.systemCost),
        },
      })
      .subscribe((cfg) => {
        this.applyStatsConfig(cfg);
        this.tariffSaved.set(true);
      });
  }

  private refresh(): void {
    this.api.getDevices().subscribe((res) => this.devices.set(res.devices));
  }

  add(): void {
    this.error.set(null);
    const body: Record<string, unknown> = {
      id: this.form.id,
      transport: this.form.transport,
    };
    if (this.form.name) body['name'] = this.form.name;
    if (this.form.transport === 'modbus_rtu') {
      body['profile'] = this.form.profile;
      body['params'] = { port: this.form.port, slave_id: this.form.slaveId };
    }
    this.api.createDevice(body).subscribe({
      next: () => {
        this.form = { id: '', name: '', transport: 'dummy', profile: '', port: '', slaveId: 1 };
        this.refresh();
      },
      error: (err) => {
        if (err?.status === 409) {
          this.error.set('A device with that ID already exists.');
        } else if (err?.status === 422) {
          this.error.set('Validation error — check the required fields for this transport.');
        } else {
          this.error.set('Could not create device.');
        }
      },
    });
  }

  toggleEnabled(d: DeviceConfig, e: Event): void {
    const enabled = (e.target as HTMLInputElement).checked;
    this.api.updateDevice(d.id, { enabled }).subscribe({ next: () => this.refresh() });
  }

  startRename(d: DeviceConfig): void {
    this.renameValue = d.name;
    this.renameId.set(d.id);
  }

  saveRename(d: DeviceConfig): void {
    this.api.updateDevice(d.id, { name: this.renameValue }).subscribe({
      next: () => {
        this.renameId.set(null);
        this.refresh();
      },
    });
  }

  remove(d: DeviceConfig): void {
    if (!confirm(`Delete device "${d.name}"?`)) return;
    this.api.deleteDevice(d.id).subscribe({ next: () => this.refresh() });
  }
}
