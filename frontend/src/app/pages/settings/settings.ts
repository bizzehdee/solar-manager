import { Component, inject, OnInit, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';

import { ApiService } from '../../core/api.service';
import { PreferencesService } from '../../core/preferences.service';
import { TranslatePipe } from '../../core/translate.pipe';
import {
  ArraySpec,
  DeviceConfig,
  DeviceProfileOption,
  DeviceTestResult,
  ForecastConfig,
  SerialPort,
  StatsConfig,
} from '../../core/models';

// Settings › Devices (plan.md §6, §11): the device registry. Lists configured devices and
// offers an inline add/edit/delete form. Single-house deployment, no auth (CLAUDE.md).
@Component({
  selector: 'app-settings',
  imports: [FormsModule, TranslatePipe],
  template: `
    <h4 class="mb-3"><i class="bi bi-gear"></i> {{ 'settings.devices.title' | translate }}</h4>

    <div class="card mb-3">
      <div class="card-header">{{ 'settings.devices.configured' | translate }}</div>
      <div class="card-body p-0">
        @if (devices().length === 0) {
          <div class="alert alert-secondary m-3 mb-0">{{ 'settings.devices.none' | translate }}</div>
        } @else {
          <div class="table-responsive">
            <table class="table align-middle mb-0">
              <thead>
                <tr>
                  <th>{{ 'settings.devices.name' | translate }}</th>
                  <th>{{ 'settings.devices.profile' | translate }}</th>
                  <th>{{ 'settings.devices.transport' | translate }}</th>
                  <th>{{ 'settings.devices.status' | translate }}</th>
                  <th>{{ 'settings.devices.capabilities' | translate }}</th>
                  <th>{{ 'settings.devices.enabled' | translate }}</th>
                  <th class="text-end">{{ 'settings.devices.actions' | translate }}</th>
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
                        {{ (d.online ? 'status.online' : 'status.offline') | translate }}
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
      <div class="card-header">{{ 'settings.devices.add' | translate }}</div>
      <div class="card-body">
        @if (error()) {
          <div class="alert alert-danger">{{ error() }}</div>
        }
        <form (ngSubmit)="add()">
          <div class="row g-3">
            <div class="col-12 col-md-4">
              <label class="form-label small text-secondary" for="dev-id">{{ 'field.id' | translate }}</label>
              <input id="dev-id" class="form-control" [(ngModel)]="form.id" name="id" required />
            </div>
            <div class="col-12 col-md-4">
              <label class="form-label small text-secondary" for="dev-name">{{ 'field.name' | translate }}</label>
              <input id="dev-name" class="form-control" [(ngModel)]="form.name" name="name" />
            </div>
            <div class="col-12 col-md-4">
              <label class="form-label small text-secondary" for="dev-transport">{{ 'field.transport' | translate }}</label>
              <select id="dev-transport" class="form-select" [(ngModel)]="form.transport" name="transport">
                <option value="dummy">dummy</option>
                <option value="modbus_rtu">modbus_rtu</option>
              </select>
            </div>
            @if (form.transport === 'modbus_rtu') {
              <div class="col-12 col-md-4">
                <label class="form-label small text-secondary" for="dev-profile">{{ 'field.profile' | translate }}</label>
                <select id="dev-profile" class="form-select" [(ngModel)]="form.profile" name="profile">
                  <option value="" disabled>{{ 'settings.devices.selectProfile' | translate }}</option>
                  @for (p of profiles(); track p.name) {
                    <option [value]="p.name">{{ p.label }}</option>
                  }
                </select>
              </div>
              <div class="col-12 col-md-4">
                <label class="form-label small text-secondary" for="dev-port">{{ 'field.serialPort' | translate }}</label>
                <div class="input-group">
                  <select id="dev-port" class="form-select" [(ngModel)]="form.port" name="port">
                    <option value="" disabled>{{ 'settings.devices.selectPort' | translate }}</option>
                    @for (p of serialPorts(); track p.device) {
                      <option [value]="p.device">
                        {{ p.device }}{{ p.description ? ' — ' + p.description : '' }}
                      </option>
                    }
                  </select>
                  <button type="button" class="btn btn-outline-secondary" (click)="refreshPorts()"
                          [title]="'settings.devices.rescan' | translate">
                    <i class="bi bi-arrow-clockwise"></i>
                  </button>
                </div>
                @if (serialPorts().length === 0) {
                  <div class="form-text">{{ 'settings.devices.noPorts' | translate }}</div>
                }
              </div>
              <div class="col-12 col-md-4">
                <label class="form-label small text-secondary" for="dev-slave">{{ 'field.slaveId' | translate }}</label>
                <input id="dev-slave" type="number" class="form-control" [(ngModel)]="form.slaveId" name="slaveId" />
              </div>
            }
          </div>
          @if (testResult(); as r) {
            <div class="alert mt-3 mb-0" [class]="r.ok ? 'alert-success' : 'alert-danger'">
              <i class="bi" [class]="r.ok ? 'bi-check-circle' : 'bi-x-circle'"></i> {{ r.message }}
            </div>
          }
          <div class="mt-3 d-flex gap-2">
            <button type="submit" class="btn btn-primary" [disabled]="!form.id">
              <i class="bi bi-plus-lg"></i> {{ 'settings.devices.add' | translate }}
            </button>
            @if (form.transport === 'modbus_rtu') {
              <button type="button" class="btn btn-outline-secondary"
                      [disabled]="testing() || !form.profile || !form.port" (click)="testConnection()">
                @if (testing()) {
                  <span class="spinner-border spinner-border-sm me-1"></span> {{ 'settings.devices.testing' | translate }}
                } @else {
                  <i class="bi bi-plug"></i> {{ 'settings.devices.testConnection' | translate }}
                }
              </button>
            }
          </div>
        </form>
      </div>
    </div>

    <!-- Tariff & economics (T051/T052): standing charge + import (flat or time-of-use windows)
         + flat export + CO₂/system cost. Rates are per kWh and the standing charge per day, in
         major currency units (e.g. enter 0.293 for 29.3p, 0.6075 for 60.75p). -->
    <div class="card mt-3">
      <div class="card-header"><i class="bi bi-cash-coin"></i> {{ 'settings.tariff.title' | translate }}</div>
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
              <label class="form-label small text-secondary" for="t-standing">Standing charge (/day)</label>
              <input id="t-standing" type="number" step="any" class="form-control" [(ngModel)]="tariff.standingCharge" name="standingCharge" />
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

          <!-- Import pricing: flat per-kWh, or time-of-use windows. -->
          <h6 class="text-secondary mt-3">Import pricing</h6>
          <div class="row g-3 align-items-end">
            <div class="col-6 col-md-3">
              <label class="form-label small text-secondary" for="t-import-mode">Mode</label>
              <select id="t-import-mode" class="form-select" [(ngModel)]="tariff.importMode" name="importMode">
                <option value="flat">Flat rate</option>
                <option value="tou">Time of use</option>
              </select>
            </div>
            <div class="col-6 col-md-3">
              <label class="form-label small text-secondary" for="t-import-flat">
                {{ tariff.importMode === 'tou' ? 'Fallback rate (/kWh)' : 'Import rate (/kWh)' }}
              </label>
              <input id="t-import-flat" type="number" step="any" class="form-control" [(ngModel)]="tariff.importFlat" name="importFlat" />
            </div>
          </div>

          @if (tariff.importMode === 'tou') {
            <p class="small text-secondary mt-2 mb-1">
              Windows are applied in order; hours not covered by any window use the fallback rate.
              A window may wrap midnight (e.g. 06:00 → 00:00).
            </p>
            @for (w of tariff.importWindows; track $index) {
              <div class="row g-2 mb-2 align-items-end">
                <div class="col-4 col-md-3">
                  <label class="form-label small text-secondary" [attr.for]="'w-start-' + $index">From</label>
                  <input [id]="'w-start-' + $index" type="time" class="form-control" [(ngModel)]="w.start" [name]="'wStart' + $index" />
                </div>
                <div class="col-4 col-md-3">
                  <label class="form-label small text-secondary" [attr.for]="'w-end-' + $index">To</label>
                  <input [id]="'w-end-' + $index" type="time" class="form-control" [(ngModel)]="w.end" [name]="'wEnd' + $index" />
                </div>
                <div class="col-4 col-md-3">
                  <label class="form-label small text-secondary" [attr.for]="'w-rate-' + $index">Rate (/kWh)</label>
                  <input [id]="'w-rate-' + $index" type="number" step="any" class="form-control" [(ngModel)]="w.rate" [name]="'wRate' + $index" />
                </div>
                <div class="col-12 col-md-3">
                  <button type="button" class="btn btn-outline-danger" (click)="removeWindow($index)">
                    <i class="bi bi-trash"></i> Remove
                  </button>
                </div>
              </div>
            }
            <div class="mt-1 mb-2">
              <button type="button" class="btn btn-sm btn-outline-secondary" (click)="addWindow()">
                <i class="bi bi-plus-lg"></i> Add window
              </button>
            </div>
          }

          <div class="mt-3">
            <button type="submit" class="btn btn-primary"><i class="bi bi-save"></i> Save tariff</button>
          </div>
        </form>
      </div>
    </div>

    <!-- Backup & data (T091): download a full SQLite snapshot, restore from one, export history. -->
    <div class="card mt-3">
      <div class="card-header"><i class="bi bi-database"></i> {{ 'settings.backup.title' | translate }}</div>
      <div class="card-body">
        @if (restoreMsg(); as msg) {
          <div class="alert alert-{{ msg.cls }}">{{ msg.text }}</div>
        }
        <div class="d-flex flex-wrap align-items-center gap-2">
          <a class="btn btn-outline-primary" href="/api/backup">
            <i class="bi bi-download"></i> Download backup
          </a>
          <input #restoreFile type="file" class="form-control" style="max-width: 20rem" accept=".sqlite,.db" />
          <button class="btn btn-outline-danger" [disabled]="restoring()" (click)="restore(restoreFile)">
            <i class="bi bi-upload"></i> Restore
          </button>
        </div>
        <p class="small text-secondary mt-2 mb-0">
          Restoring replaces the live database with the uploaded backup. Per-metric CSV export is
          on the History view.
        </p>
      </div>
    </div>

    <!-- Formatting & locale (T093): drives date/number formatting (applied on reload). -->
    <div class="card mt-3">
      <div class="card-header"><i class="bi bi-translate"></i> {{ 'settings.locale.title' | translate }}</div>
      <div class="card-body">
        @if (localeSaved()) {
          <div class="alert alert-success">Saved — reloading to apply the new locale…</div>
        }
        <div class="row g-3 align-items-end">
          <div class="col-12 col-md-5">
            <label class="form-label small text-secondary" for="loc">{{ 'settings.locale.field' | translate }}</label>
            <select id="loc" class="form-select" [(ngModel)]="localeChoice" name="locale">
              @for (l of prefs.supported; track l.id) {
                <option [value]="l.id">{{ l.label }}</option>
              }
            </select>
          </div>
          <div class="col-12 col-md-4">
            <button type="button" class="btn btn-primary" (click)="saveLocale()">
              <i class="bi bi-save"></i> {{ 'settings.locale.save' | translate }}
            </button>
          </div>
        </div>
        <p class="small text-secondary mt-2 mb-0">
          Currency is configured with the tariff above. The locale controls how dates and numbers
          are formatted, and the UI language where a translation is available (English otherwise).
        </p>
      </div>
    </div>

    <!-- Solar array & site (T064): drives the Phase 4 forecast model. Site location + overall
         derating, the PV array geometry (one row per string), and the battery operating window. -->
    <div class="card mt-3">
      <div class="card-header"><i class="bi bi-sun"></i> {{ 'settings.solar.title' | translate }}</div>
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
              <div class="input-group">
                <input id="f-pr" type="number" step="any" class="form-control" [(ngModel)]="forecast.site.performance_ratio" name="pr" />
                <button type="button" class="btn btn-outline-secondary" (click)="calibratePr()"
                        title="Suggest from measured history">
                  <i class="bi bi-magic"></i>
                </button>
              </div>
            </div>
          </div>
          @if (calibrateMsg(); as msg) {
            <div class="alert alert-{{ msg.cls }} py-2">{{ msg.text }}</div>
          }

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

  // Add-device form helpers: enumerated ports/profiles + connection-test feedback.
  readonly serialPorts = signal<SerialPort[]>([]);
  readonly profiles = signal<DeviceProfileOption[]>([]);
  readonly testing = signal(false);
  readonly testResult = signal<DeviceTestResult | null>(null);

  form = {
    id: '',
    name: '',
    transport: 'dummy',
    profile: '',
    port: '',
    slaveId: 1,
  };

  // Tariff form (T051/T052): standing charge + flat-or-TOU import + flat export. Import
  // windows use HH:MM strings in the form and convert to/from the backend's hour-floats.
  readonly tariffSaved = signal(false);
  tariff = {
    currency: 'GBP',
    standingCharge: 0,
    importMode: 'flat' as 'flat' | 'tou',
    importFlat: 0,
    importWindows: [] as { start: string; end: string; rate: number }[],
    exportRate: 0,
    co2Intensity: 0,
    systemCost: 0,
  };

  // Backup & restore (T091).
  readonly restoring = signal(false);
  readonly restoreMsg = signal<{ cls: string; text: string } | null>(null);

  // Locale (T093).
  readonly prefs = inject(PreferencesService);
  localeChoice = this.prefs.locale();
  readonly localeSaved = signal(false);

  // Forecast config form (T064) — site/array/battery driving the Phase 4 forecast.
  readonly forecastSaved = signal(false);
  readonly calibrateMsg = signal<{ cls: string; text: string } | null>(null);
  forecast: ForecastConfig = {
    site: { lat: 0, lon: 0, performance_ratio: 0.85 },
    arrays: [],
    battery: { capacity_wh: 0, min_soc_pct: 0, max_soc_pct: 100 },
  };

  ngOnInit(): void {
    this.refresh();
    this.refreshPorts();
    this.loadProfiles();
    this.loadTariff();
    this.loadForecast();
  }

  /** Re-enumerate the host's serial ports (also the rescan button). */
  refreshPorts(): void {
    this.api.getSerialPorts().subscribe((res) => this.serialPorts.set(res.ports));
  }

  private loadProfiles(): void {
    this.api.getProfiles().subscribe((res) => this.profiles.set(res.profiles));
  }

  /** Probe the connection for the values currently in the Add-device form. */
  testConnection(): void {
    this.testing.set(true);
    this.testResult.set(null);
    this.api
      .testDevice({
        transport: this.form.transport,
        profile: this.form.profile,
        params: { port: this.form.port, slave_id: this.form.slaveId },
      })
      .subscribe({
        next: (r) => {
          this.testResult.set(r);
          this.testing.set(false);
        },
        error: () => {
          this.testResult.set({ ok: false, message: 'Could not run the connection test.' });
          this.testing.set(false);
        },
      });
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

  /** Suggest a performance ratio from measured history and pre-fill the field (T096). */
  calibratePr(): void {
    this.calibrateMsg.set(null);
    this.api.getForecastCalibration().subscribe({
      next: (c) => {
        if (c.suggested_pr === null) {
          this.calibrateMsg.set({ cls: 'secondary', text: 'Not enough generation yet today to suggest a ratio.' });
          return;
        }
        this.forecast = { ...this.forecast, site: { ...this.forecast.site, performance_ratio: c.suggested_pr } };
        this.calibrateMsg.set({
          cls: 'info',
          text: `Suggested ${c.suggested_pr} (measured ${c.actual_wh} Wh vs modelled ${c.expected_wh} Wh so far). Save to apply.`,
        });
      },
      error: () => this.calibrateMsg.set({ cls: 'danger', text: 'Could not calibrate.' }),
    });
  }

  /** Persist the chosen locale and reload so LOCALE_ID re-resolves (T093). */
  saveLocale(): void {
    this.localeSaved.set(false);
    this.prefs.save(this.localeChoice).subscribe(() => {
      this.localeSaved.set(true);
      this.reloadApp();
    });
  }

  /** Isolated so tests don't trigger a real navigation. */
  reloadApp(): void {
    try {
      location.reload();
    } catch {
      /* not available in tests */
    }
  }

  private loadTariff(): void {
    this.api.getStatsConfig().subscribe((cfg) => this.applyStatsConfig(cfg));
  }

  /** Map the API config into the tariff form fields (TOU windows ⇒ HH:MM). */
  private applyStatsConfig(cfg: StatsConfig): void {
    const imp = cfg.tariff.import_rate;
    const windows = imp?.windows ?? [];
    this.tariff = {
      currency: cfg.tariff.currency,
      standingCharge: cfg.tariff.standing_charge ?? 0,
      importMode: windows.length ? 'tou' : 'flat',
      importFlat: imp?.flat ?? 0,
      importWindows: windows.map((w) => ({
        start: hourToHHMM(w.start_hour),
        end: hourToHHMM(w.end_hour),
        rate: w.rate,
      })),
      exportRate: cfg.tariff.export_rate?.flat ?? 0,
      co2Intensity: cfg.economics?.['co2_intensity_g_per_kwh'] ?? 0,
      systemCost: cfg.economics?.['system_cost'] ?? 0,
    };
  }

  /** Append a blank time-of-use window (defaults to a full off-peak-ish midnight start). */
  addWindow(): void {
    this.tariff.importWindows = [...this.tariff.importWindows, { start: '00:00', end: '06:00', rate: 0 }];
  }

  removeWindow(index: number): void {
    this.tariff.importWindows = this.tariff.importWindows.filter((_, i) => i !== index);
  }

  saveTariff(): void {
    this.tariffSaved.set(false);
    // Bare number ⇒ flat (backend treats it as such); object ⇒ flat fallback + TOU windows.
    const importRate =
      this.tariff.importMode === 'tou'
        ? {
            flat: Number(this.tariff.importFlat),
            windows: this.tariff.importWindows.map((w) => ({
              start_hour: hhmmToHour(w.start),
              end_hour: hhmmToHour(w.end),
              rate: Number(w.rate),
            })),
          }
        : Number(this.tariff.importFlat);
    this.api
      .putStatsConfig({
        tariff: {
          currency: this.tariff.currency,
          standing_charge: Number(this.tariff.standingCharge),
          import_rate: importRate,
          export_rate: Number(this.tariff.exportRate),
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

  /** Restore the DB from the selected backup file (T091). */
  restore(input: HTMLInputElement): void {
    const file = input.files?.[0];
    if (!file) {
      this.restoreMsg.set({ cls: 'warning', text: 'Choose a backup file first.' });
      return;
    }
    this.restoring.set(true);
    this.restoreMsg.set(null);
    this.api.restoreBackup(file).subscribe({
      next: () => {
        this.restoring.set(false);
        this.restoreMsg.set({ cls: 'success', text: 'Database restored. Reload to see the restored data.' });
        this.refresh();
      },
      error: (err) => {
        this.restoring.set(false);
        const text = err?.status === 422 ? 'That file is not a valid SolarVolt backup.' : 'Restore failed.';
        this.restoreMsg.set({ cls: 'danger', text });
      },
    });
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
        this.testResult.set(null);
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

/** "HH:MM" → fractional hour-of-day (e.g. "06:30" → 6.5). Empty/garbage → 0. */
function hhmmToHour(s: string): number {
  const [h, m] = (s || '').split(':');
  const hours = Number(h);
  const mins = Number(m);
  return (Number.isFinite(hours) ? hours : 0) + (Number.isFinite(mins) ? mins : 0) / 60;
}

/** Fractional hour-of-day → "HH:MM" (e.g. 6.5 → "06:30"; 24 wraps to "00:00"). */
function hourToHHMM(hour: number): string {
  const h = Math.floor(hour) % 24;
  const m = Math.round((hour - Math.floor(hour)) * 60);
  // Carry a rounded-up 60 minutes into the hour.
  const hh = m === 60 ? (h + 1) % 24 : h;
  const mm = m === 60 ? 0 : m;
  return `${String(hh).padStart(2, '0')}:${String(mm).padStart(2, '0')}`;
}
