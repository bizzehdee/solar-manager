import { Component, inject, OnInit, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Router } from '@angular/router';

import { ApiService } from '../../core/api.service';
import { DashboardsService } from '../../core/dashboards.service';
import { DialogService } from '../../core/dialog.service';
import { downloadDashboard, parseDashboard } from '../../core/dashboard-file';
import { unknownWidgetTypes } from '../../shared/widget-registry';
import { PreferencesService } from '../../core/preferences.service';
import { TranslatePipe } from '../../core/translate.pipe';
import { DiagnosticsPage } from '../diagnostics/diagnostics';
import {
  ArraySpec,
  DashboardConfig,
  DeviceConfig,
  DeviceProfileOption,
  DeviceTestResult,
  ForecastConfig,
  MqttConfig,
  ReadingsWebhookConfig,
  SerialPort,
  StatsConfig,
} from '../../core/models';

// Settings › Devices (plan.md §6, §11): the device registry. Lists configured devices and
// offers an inline add/edit/delete form. Single-house deployment, no auth (CLAUDE.md).
type SettingsTab = 'devices' | 'solar' | 'tariff' | 'notifications' | 'dashboards' | 'system' | 'diagnostics';

@Component({
  selector: 'app-settings',
  imports: [FormsModule, TranslatePipe, DiagnosticsPage],
  template: `
    <h4 class="mb-3"><i class="bi bi-gear"></i> {{ 'settings.title' | translate }}</h4>

    <ul class="nav nav-tabs mb-3" role="tablist">
      @for (t of tabs; track t.id) {
        <li class="nav-item" role="presentation">
          <button class="nav-link" type="button" role="tab"
                  [class.active]="tab() === t.id" [attr.aria-selected]="tab() === t.id"
                  (click)="tab.set(t.id)">
            <i class="bi {{ t.icon }}"></i> {{ t.labelKey | translate }}
          </button>
        </li>
      }
    </ul>

    @if (tab() === 'devices') {
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
                <option value="solarman_v5">solarman_v5</option>
              </select>
            </div>
            <!-- A profile is needed for any real transport (the same map serves RTU + SolarmanV5). -->
            @if (form.transport !== 'dummy') {
              <div class="col-12 col-md-4">
                <label class="form-label small text-secondary" for="dev-profile">{{ 'field.profile' | translate }}</label>
                <select id="dev-profile" class="form-select" [(ngModel)]="form.profile" name="profile">
                  <option value="" disabled>{{ 'settings.devices.selectProfile' | translate }}</option>
                  @for (p of profiles(); track p.name) {
                    <option [value]="p.name">{{ p.label }}</option>
                  }
                </select>
              </div>
            }
            @if (form.transport === 'solarman_v5') {
              <div class="col-12 col-md-4">
                <label class="form-label small text-secondary" for="dev-host">Logger host / IP</label>
                <input id="dev-host" class="form-control" [(ngModel)]="form.host" name="host" placeholder="e.g. 192.168.1.50" />
              </div>
              <div class="col-12 col-md-4">
                <label class="form-label small text-secondary" for="dev-serial">Logger serial</label>
                <input id="dev-serial" type="number" class="form-control" [(ngModel)]="form.serial" name="serial" placeholder="from the stick / Solarman app" />
              </div>
              <div class="col-6 col-md-4">
                <label class="form-label small text-secondary" for="dev-sport">Port</label>
                <input id="dev-sport" type="number" class="form-control" [(ngModel)]="form.solarmanPort" name="solarmanPort" />
              </div>
              <div class="col-6 col-md-4">
                <label class="form-label small text-secondary" for="dev-sslave">{{ 'field.slaveId' | translate }}</label>
                <input id="dev-sslave" type="number" class="form-control" [(ngModel)]="form.slaveId" name="solarmanSlaveId" />
              </div>
            }
            @if (form.transport === 'modbus_rtu') {
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
            @if (form.transport !== 'dummy') {
              <button type="button" class="btn btn-outline-secondary"
                      [disabled]="testing() || !canTest()" (click)="testConnection()">
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
    }

    <!-- Tariff & economics (T051/T052): standing charge + import (flat or time-of-use windows)
         + flat export + CO₂/system cost. Rates are per kWh and the standing charge per day, in
         major currency units (e.g. enter 0.293 for 29.3p, 0.6075 for 60.75p). -->
    @if (tab() === 'tariff') {
    <div class="card">
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
    }

    <!-- Dashboards management (L06 / T_DB6): list all dashboards with rename/export/delete, plus
         import from a JSON file. Built-ins (Now, History) can be exported but not renamed/deleted. -->
    @if (tab() === 'dashboards') {
    <div class="card">
      <div class="card-header d-flex align-items-center justify-content-between">
        <span><i class="bi bi-grid-1x2"></i> Dashboards</span>
        <div class="d-flex gap-2">
          <button class="btn btn-sm btn-outline-secondary" (click)="createDashboard()">
            <i class="bi bi-plus-lg"></i> New
          </button>
          <input #importFile type="file" accept=".json,application/json" class="d-none" (change)="importDashboard(importFile)" />
          <button class="btn btn-sm btn-outline-secondary" (click)="importFile.click()">
            <i class="bi bi-upload"></i> Import
          </button>
        </div>
      </div>
      <div class="card-body p-0">
        @if (dashboardsMsg(); as msg) { <div class="alert alert-{{ msg.cls }} m-3 mb-0 py-2">{{ msg.text }}</div> }
        <table class="table align-middle mb-0">
          <thead>
            <tr><th>Name</th><th>Type</th><th>Widgets</th><th class="text-end">Actions</th></tr>
          </thead>
          <tbody>
            @for (d of dashboards.dashboards(); track d.id) {
              <tr>
                <td class="fw-semibold">{{ d.name }}</td>
                <td>
                  <span class="badge" [class]="d.builtin ? 'text-bg-secondary' : 'text-bg-info'">
                    {{ d.builtin ? 'built-in' : 'custom' }}
                  </span>
                </td>
                <td>{{ d.widgets.length }}</td>
                <td class="text-end text-nowrap">
                  <button class="btn btn-sm btn-outline-secondary me-1" (click)="exportDashboard(d)" title="Export JSON">
                    <i class="bi bi-download"></i>
                  </button>
                  @if (!d.builtin) {
                    <button class="btn btn-sm btn-outline-secondary me-1" (click)="renameDashboard(d)" title="Rename">
                      <i class="bi bi-pencil"></i>
                    </button>
                    <button class="btn btn-sm btn-outline-danger" (click)="deleteDashboard(d)" title="Delete">
                      <i class="bi bi-trash"></i>
                    </button>
                  }
                </td>
              </tr>
            }
          </tbody>
        </table>
      </div>
    </div>
    }

    <!-- Backup & data (T091): download a full SQLite snapshot, restore from one, export history. -->
    @if (tab() === 'system') {
    <div class="card">
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
    }

    <!-- Notification channels (L10): how fired alerts are pushed (in addition to the in-app inbox).
         Each channel is selectable per rule once configured. Off the hot path — a dead channel never
         blocks monitoring. Secrets are stored in the local DB (single-house, no-auth deployment). -->
    @if (tab() === 'notifications') {
    <div class="card">
      <div class="card-header"><i class="bi bi-send"></i> Notification channels</div>
      <div class="card-body">
        @if (channelsMsg(); as msg) { <div class="alert alert-{{ msg.cls }} py-2">{{ msg.text }}</div> }
        <p class="small text-secondary">
          The in-app inbox always records alerts. Configure any of these to also push them, then pick
          channels per rule on the Alerts page. Save before sending a test.
        </p>

        <h6 class="text-secondary d-flex align-items-center gap-2">Webhook @if (isConfigured('webhook')) { <span class="badge text-bg-success">configured</span> }</h6>
        <div class="row g-2 mb-2 align-items-end">
          <div class="col-12 col-md-8">
            <input class="form-control" [(ngModel)]="channels.webhook.url" name="chWhUrl" placeholder="POST URL" aria-label="Webhook URL" />
          </div>
          <div class="col-12 col-md-4">
            <button type="button" class="btn btn-outline-secondary btn-sm" (click)="testChannel('webhook')" [disabled]="!isConfigured('webhook')">Test</button>
          </div>
        </div>

        <h6 class="text-secondary d-flex align-items-center gap-2 mt-3">Telegram @if (isConfigured('telegram')) { <span class="badge text-bg-success">configured</span> }</h6>
        <div class="row g-2 mb-2 align-items-end">
          <div class="col-6 col-md-5"><input class="form-control" [(ngModel)]="channels.telegram.bot_token" name="chTgTok" placeholder="Bot token" aria-label="Telegram bot token" /></div>
          <div class="col-6 col-md-4"><input class="form-control" [(ngModel)]="channels.telegram.chat_id" name="chTgChat" placeholder="Chat ID" aria-label="Telegram chat ID" /></div>
          <div class="col-12 col-md-3"><button type="button" class="btn btn-outline-secondary btn-sm" (click)="testChannel('telegram')" [disabled]="!isConfigured('telegram')">Test</button></div>
        </div>

        <h6 class="text-secondary d-flex align-items-center gap-2 mt-3">ntfy @if (isConfigured('ntfy')) { <span class="badge text-bg-success">configured</span> }</h6>
        <div class="row g-2 mb-2 align-items-end">
          <div class="col-6 col-md-5"><input class="form-control" [(ngModel)]="channels.ntfy.topic" name="chNtTopic" placeholder="Topic" aria-label="ntfy topic" /></div>
          <div class="col-6 col-md-4"><input class="form-control" [(ngModel)]="channels.ntfy.server" name="chNtServer" placeholder="ntfy.sh or your server URL" aria-label="ntfy server" /></div>
          <div class="col-12 col-md-3"><button type="button" class="btn btn-outline-secondary btn-sm" (click)="testChannel('ntfy')" [disabled]="!isConfigured('ntfy')">Test</button></div>
        </div>

        <h6 class="text-secondary d-flex align-items-center gap-2 mt-3">Gotify @if (isConfigured('gotify')) { <span class="badge text-bg-success">configured</span> }</h6>
        <div class="row g-2 mb-2 align-items-end">
          <div class="col-6 col-md-5"><input class="form-control" [(ngModel)]="channels.gotify.url" name="chGoUrl" placeholder="Server URL" aria-label="Gotify URL" /></div>
          <div class="col-6 col-md-4"><input class="form-control" [(ngModel)]="channels.gotify.token" name="chGoTok" placeholder="App token" aria-label="Gotify token" /></div>
          <div class="col-12 col-md-3"><button type="button" class="btn btn-outline-secondary btn-sm" (click)="testChannel('gotify')" [disabled]="!isConfigured('gotify')">Test</button></div>
        </div>

        <h6 class="text-secondary d-flex align-items-center gap-2 mt-3">Pushover @if (isConfigured('pushover')) { <span class="badge text-bg-success">configured</span> }</h6>
        <div class="row g-2 mb-2 align-items-end">
          <div class="col-6 col-md-5"><input class="form-control" [(ngModel)]="channels.pushover.token" name="chPoTok" placeholder="API token" aria-label="Pushover token" /></div>
          <div class="col-6 col-md-4"><input class="form-control" [(ngModel)]="channels.pushover.user" name="chPoUser" placeholder="User key" aria-label="Pushover user key" /></div>
          <div class="col-12 col-md-3"><button type="button" class="btn btn-outline-secondary btn-sm" (click)="testChannel('pushover')" [disabled]="!isConfigured('pushover')">Test</button></div>
        </div>

        <h6 class="text-secondary d-flex align-items-center gap-2 mt-3">Email (SMTP) @if (isConfigured('email')) { <span class="badge text-bg-success">configured</span> }</h6>
        <div class="row g-2 mb-2 align-items-end">
          <div class="col-6 col-md-4"><label class="form-label small text-secondary mb-0">Host</label><input class="form-control" [(ngModel)]="channels.email.host" name="chEmHost" aria-label="SMTP host" /></div>
          <div class="col-6 col-md-2"><label class="form-label small text-secondary mb-0">Port</label><input type="number" class="form-control" [(ngModel)]="channels.email.port" name="chEmPort" aria-label="SMTP port" /></div>
          <div class="col-6 col-md-3"><label class="form-label small text-secondary mb-0">Username</label><input class="form-control" [(ngModel)]="channels.email.username" name="chEmUser" aria-label="SMTP username" /></div>
          <div class="col-6 col-md-3"><label class="form-label small text-secondary mb-0">Password</label><input type="password" class="form-control" [(ngModel)]="channels.email.password" name="chEmPass" aria-label="SMTP password" /></div>
          <div class="col-6 col-md-4"><label class="form-label small text-secondary mb-0">From</label><input class="form-control" [(ngModel)]="channels.email.from" name="chEmFrom" aria-label="From address" /></div>
          <div class="col-6 col-md-4"><label class="form-label small text-secondary mb-0">To</label><input class="form-control" [(ngModel)]="channels.email.to" name="chEmTo" aria-label="To address" /></div>
          <div class="col-6 col-md-2">
            <div class="form-check mt-4"><input class="form-check-input" type="checkbox" id="ch-em-tls" [(ngModel)]="channels.email.use_tls" name="chEmTls" /><label class="form-check-label small" for="ch-em-tls">STARTTLS</label></div>
          </div>
          <div class="col-6 col-md-2"><button type="button" class="btn btn-outline-secondary btn-sm mt-4" (click)="testChannel('email')" [disabled]="!isConfigured('email')">Test</button></div>
        </div>

        <div class="mt-3">
          <button type="button" class="btn btn-primary" (click)="saveChannels()"><i class="bi bi-save"></i> Save channels</button>
        </div>
      </div>
    </div>

    <!-- Integrations › outbound readings webhook (L09): periodically POST the latest snapshot to a
         user URL (Node-RED / IFTTT / custom). Off the hot path — a dead endpoint never blocks monitoring. -->
    <div class="card mt-3">
      <div class="card-header"><i class="bi bi-broadcast"></i> Outbound readings webhook</div>
      <div class="card-body">
        @if (webhookMsg(); as msg) { <div class="alert alert-{{ msg.cls }} py-2">{{ msg.text }}</div> }
        <div class="row g-3 align-items-end">
          <div class="col-12 col-md-6">
            <label class="form-label small text-secondary" for="wh-url">URL</label>
            <input id="wh-url" class="form-control" [(ngModel)]="webhook.url" name="whUrl" placeholder="your endpoint URL" />
          </div>
          <div class="col-6 col-md-3">
            <label class="form-label small text-secondary" for="wh-int">Interval (s)</label>
            <input id="wh-int" type="number" min="5" class="form-control" [(ngModel)]="webhook.interval_s" name="whInterval" />
          </div>
          <div class="col-6 col-md-3">
            <div class="form-check form-switch mt-md-4">
              <input class="form-check-input" type="checkbox" role="switch" id="wh-en" [(ngModel)]="webhook.enabled" name="whEnabled" />
              <label class="form-check-label" for="wh-en">Enabled</label>
            </div>
          </div>
        </div>
        <div class="mt-3 d-flex gap-2">
          <button type="button" class="btn btn-primary" (click)="saveWebhook()"><i class="bi bi-save"></i> Save</button>
          <button type="button" class="btn btn-outline-secondary" (click)="testWebhook()" [disabled]="!webhook.url">
            <i class="bi bi-send"></i> Send test
          </button>
        </div>
        <p class="small text-secondary mt-2 mb-0">
          POSTs the latest normalized snapshot as JSON on the chosen interval. Save before sending a
          test. A failing endpoint is logged and never disrupts monitoring; alert egress is set per rule.
        </p>
      </div>
    </div>

    <!-- MQTT publisher + Home Assistant discovery (L07): publish each snapshot to a broker and
         emit HA discovery configs so every metric becomes an HA sensor with no manual YAML. Off the
         hot path — an unreachable broker is logged and never disrupts monitoring. -->
    <div class="card mt-3">
      <div class="card-header"><i class="bi bi-broadcast-pin"></i> MQTT + Home Assistant</div>
      <div class="card-body">
        @if (mqttMsg(); as msg) { <div class="alert alert-{{ msg.cls }} py-2">{{ msg.text }}</div> }
        <div class="row g-3 align-items-end">
          <div class="col-12 col-md-5">
            <label class="form-label small text-secondary" for="mq-host">Broker host</label>
            <input id="mq-host" class="form-control" [(ngModel)]="mqtt.host" name="mqHost" placeholder="e.g. 192.168.1.10 or mqtt.lan" />
          </div>
          <div class="col-6 col-md-2">
            <label class="form-label small text-secondary" for="mq-port">Port</label>
            <input id="mq-port" type="number" class="form-control" [(ngModel)]="mqtt.port" name="mqPort" />
          </div>
          <div class="col-6 col-md-3">
            <label class="form-label small text-secondary" for="mq-int">Interval (s)</label>
            <input id="mq-int" type="number" min="5" class="form-control" [(ngModel)]="mqtt.interval_s" name="mqInterval" />
          </div>
          <div class="col-6 col-md-2">
            <div class="form-check form-switch mt-md-4">
              <input class="form-check-input" type="checkbox" role="switch" id="mq-en" [(ngModel)]="mqtt.enabled" name="mqEnabled" />
              <label class="form-check-label" for="mq-en">Enabled</label>
            </div>
          </div>
          <div class="col-6 col-md-4">
            <label class="form-label small text-secondary" for="mq-user">Username (optional)</label>
            <input id="mq-user" class="form-control" [(ngModel)]="mqtt.username" name="mqUser" autocomplete="off" />
          </div>
          <div class="col-6 col-md-4">
            <label class="form-label small text-secondary" for="mq-pass">Password (optional)</label>
            <input id="mq-pass" type="password" class="form-control" [(ngModel)]="mqtt.password" name="mqPass" autocomplete="off" />
          </div>
          <div class="col-6 col-md-2">
            <div class="form-check form-switch mt-md-4">
              <input class="form-check-input" type="checkbox" role="switch" id="mq-tls" [(ngModel)]="mqtt.tls" name="mqTls" />
              <label class="form-check-label" for="mq-tls">TLS</label>
            </div>
          </div>
          <div class="col-6 col-md-4">
            <label class="form-label small text-secondary" for="mq-base">Base topic</label>
            <input id="mq-base" class="form-control" [(ngModel)]="mqtt.base_topic" name="mqBase" />
          </div>
          <div class="col-12 col-md-5">
            <label class="form-label small text-secondary" for="mq-dprefix">HA discovery prefix</label>
            <input id="mq-dprefix" class="form-control" [(ngModel)]="mqtt.discovery_prefix" name="mqDPrefix" [disabled]="!mqtt.discovery" />
          </div>
          <div class="col-12 col-md-3">
            <div class="form-check form-switch mt-md-4">
              <input class="form-check-input" type="checkbox" role="switch" id="mq-disc" [(ngModel)]="mqtt.discovery" name="mqDisc" />
              <label class="form-check-label" for="mq-disc">HA discovery</label>
            </div>
          </div>
        </div>
        <div class="mt-3 d-flex gap-2">
          <button type="button" class="btn btn-primary" (click)="saveMqtt()"><i class="bi bi-save"></i> Save</button>
          <button type="button" class="btn btn-outline-secondary" (click)="testMqtt()" [disabled]="!mqtt.host">
            <i class="bi bi-broadcast"></i> Publish test
          </button>
        </div>
        <p class="small text-secondary mt-2 mb-0">
          Publishes one compact JSON state message per device to <code>{{ mqtt.base_topic || 'solarvolt' }}/&lt;device&gt;/state</code>.
          With <strong>HA discovery</strong> on, every metric appears automatically as a Home Assistant sensor — no YAML.
          Save before testing.
        </p>
      </div>
    </div>
    }

    <!-- Formatting & locale (T093): drives date/number formatting (applied on reload). -->
    @if (tab() === 'system') {
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
          Currency is configured on the Tariff tab. The locale controls how dates and numbers
          are formatted, and the UI language where a translation is available (English otherwise).
        </p>
      </div>
    </div>
    }

    <!-- Solar array & site (T064): drives the Phase 4 forecast model. Site location + overall
         derating, the PV array geometry (one row per string), and the battery operating window. -->
    @if (tab() === 'solar') {
    <div class="card">
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
    }

    <!-- Diagnostics (T092): a read-only operational snapshot, embedded here (no longer a top-level
         nav item). The component loads its own data when this tab is first opened. -->
    @if (tab() === 'diagnostics') {
      <app-diagnostics />
    }
  `,
})
export class SettingsPage implements OnInit {
  private readonly api = inject(ApiService);
  readonly dashboards = inject(DashboardsService);
  private readonly dialog = inject(DialogService);
  private readonly router = inject(Router);
  readonly dashboardsMsg = signal<{ cls: string; text: string } | null>(null);

  // Tabbed layout: each tab groups one concern. Diagnostics is embedded here (T092) rather than
  // being its own sidebar entry. Devices is the default landing tab.
  readonly tab = signal<SettingsTab>('devices');
  readonly tabs: { id: SettingsTab; labelKey: string; icon: string }[] = [
    { id: 'devices', labelKey: 'settings.tab.devices', icon: 'bi-hdd-network' },
    { id: 'solar', labelKey: 'settings.tab.solar', icon: 'bi-sun' },
    { id: 'tariff', labelKey: 'settings.tab.tariff', icon: 'bi-cash-coin' },
    { id: 'notifications', labelKey: 'settings.tab.notifications', icon: 'bi-send' },
    { id: 'dashboards', labelKey: 'settings.tab.dashboards', icon: 'bi-grid-1x2' },
    { id: 'system', labelKey: 'settings.tab.system', icon: 'bi-sliders' },
    { id: 'diagnostics', labelKey: 'settings.tab.diagnostics', icon: 'bi-clipboard-pulse' },
  ];

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
    // SolarmanV5 (L01): TCP to a data-logger stick.
    host: '',
    serial: '',
    solarmanPort: 8899,
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

  // Outbound readings webhook (L09).
  readonly webhookMsg = signal<{ cls: string; text: string } | null>(null);
  webhook: ReadingsWebhookConfig = { url: '', interval_s: 60, enabled: false };

  // MQTT publisher + Home Assistant discovery (L07).
  readonly mqttMsg = signal<{ cls: string; text: string } | null>(null);
  mqtt: MqttConfig = {
    enabled: false, host: '', port: 1883, username: '', password: '', tls: false,
    base_topic: 'solarvolt', interval_s: 30, discovery: true, discovery_prefix: 'homeassistant',
  };

  // Notification channels (L10). One form-model per provider; `configured` reflects which are
  // fully set up server-side (drives the Test buttons + the per-rule channel list on Alerts).
  readonly channelsMsg = signal<{ cls: string; text: string } | null>(null);
  readonly configured = signal<string[]>([]);
  channels = {
    webhook: { url: '' },
    telegram: { bot_token: '', chat_id: '' },
    ntfy: { topic: '', server: '' },
    gotify: { url: '', token: '' },
    pushover: { token: '', user: '' },
    email: { host: '', port: 587, username: '', password: '', from: '', to: '', use_tls: true },
  };

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
    this.loadWebhook();
    this.loadMqtt();
    this.loadChannels();
    this.dashboards.refresh();
  }

  // --- Dashboards management (L06 / T_DB6) ---
  async createDashboard(): Promise<void> {
    const name = await this.dialog.prompt({ title: 'New dashboard', label: 'Name', confirmText: 'Create' });
    if (!name) return;
    this.dashboards.create(name).subscribe({
      next: () => this.flashDashboards('success', `Created "${name}".`),
      error: () => this.flashDashboards('danger', 'Could not create the dashboard.'),
    });
  }

  async renameDashboard(d: DashboardConfig): Promise<void> {
    const name = await this.dialog.prompt({ title: 'Rename dashboard', label: 'Name', value: d.name, confirmText: 'Rename' });
    if (!name || name === d.name) return;
    this.dashboards.rename(d, name).subscribe({
      next: () => this.flashDashboards('success', 'Renamed.'),
      error: () => this.flashDashboards('danger', 'Could not rename.'),
    });
  }

  async deleteDashboard(d: DashboardConfig): Promise<void> {
    const ok = await this.dialog.confirm({
      title: 'Delete dashboard',
      message: `Delete dashboard "${d.name}"? This can't be undone.`,
      confirmText: 'Delete',
      danger: true,
    });
    if (!ok) return;
    this.dashboards.remove(d.id).subscribe({
      next: () => this.flashDashboards('success', `Deleted "${d.name}".`),
      error: () => this.flashDashboards('danger', 'Could not delete (built-ins are protected).'),
    });
  }

  exportDashboard(d: DashboardConfig): void {
    this.api.getDashboard(d.id).subscribe((cfg) => downloadDashboard(cfg));
  }

  importDashboard(input: HTMLInputElement): void {
    const file = input.files?.[0];
    if (!file) return;
    file.text().then((text) => {
      input.value = '';
      let parsed: { name: string; widgets: DashboardConfig['widgets'] };
      try {
        parsed = parseDashboard(text);
      } catch {
        this.flashDashboards('danger', "That file isn't a valid dashboard JSON.");
        return;
      }
      // Unknown widget types are a warning, not a hard error — they render a placeholder.
      const unknown = unknownWidgetTypes(parsed.widgets);
      const name = this.dashboards.uniqueName(parsed.name);
      const id = this.dashboards.uniqueId(name);
      this.api.putDashboard(id, { name, widgets: parsed.widgets }).subscribe({
        next: (saved) => {
          this.dashboards.refresh();
          if (unknown.length) {
            this.flashDashboards('warning', `Imported "${name}" — unknown widget type(s): ${unknown.join(', ')}.`);
          } else {
            this.flashDashboards('success', `Imported "${name}".`);
            this.router.navigate(['dashboard', saved.id]); // jump to a clean import
          }
        },
        error: () => this.flashDashboards('danger', 'Could not import the dashboard.'),
      });
    });
  }

  private flashDashboards(cls: string, text: string): void {
    this.dashboardsMsg.set({ cls, text });
    setTimeout(() => this.dashboardsMsg.set(null), 4000);
  }

  // --- MQTT publisher + HA discovery (L07) ---
  private loadMqtt(): void {
    this.api.getMqtt().subscribe({ next: (c) => (this.mqtt = c) });
  }

  saveMqtt(): void {
    this.api.putMqtt(this.mqtt).subscribe({
      next: (c) => { this.mqtt = c; this.flashMqtt('success', 'Saved.'); },
      error: () => this.flashMqtt('danger', 'Could not save the MQTT settings.'),
    });
  }

  testMqtt(): void {
    this.api.testMqtt().subscribe({
      next: (r) => this.flashMqtt('success', `Published ${r.published} message(s) to the broker.`),
      error: (err) => this.flashMqtt('danger', err?.error?.detail || 'MQTT publish failed.'),
    });
  }

  private flashMqtt(cls: string, text: string): void {
    this.mqttMsg.set({ cls, text });
    setTimeout(() => this.mqttMsg.set(null), 4000);
  }

  // --- Notification channels (L10) ---
  isConfigured = (name: string): boolean => this.configured().includes(name);

  private loadChannels(): void {
    this.api.getAlertChannels().subscribe({
      next: (r) => {
        // Merge saved config over the form defaults so untouched providers keep their defaults.
        const forms = this.channels as unknown as Record<string, Record<string, unknown>>;
        for (const key of Object.keys(forms)) {
          const saved = r.channels[key];
          if (saved) forms[key] = { ...forms[key], ...saved };
        }
        this.configured.set(r.configured);
      },
    });
  }

  saveChannels(): void {
    this.api.putAlertChannels(this.channels as unknown as Record<string, Record<string, unknown>>).subscribe({
      next: (r) => {
        this.configured.set(r.configured);
        this.flashChannels('success', 'Saved.');
      },
      error: () => this.flashChannels('danger', 'Could not save the channels.'),
    });
  }

  testChannel(name: string): void {
    this.api.testAlertChannel(name).subscribe({
      next: () => this.flashChannels('success', `Test sent via ${name}.`),
      error: (err) => this.flashChannels('danger', err?.error?.detail || `Test via ${name} failed.`),
    });
  }

  private flashChannels(cls: string, text: string): void {
    this.channelsMsg.set({ cls, text });
    setTimeout(() => this.channelsMsg.set(null), 4000);
  }

  private loadWebhook(): void {
    this.api.getReadingsWebhook().subscribe({
      next: (c) => (this.webhook = { url: c.url ?? '', interval_s: c.interval_s, enabled: c.enabled }),
    });
  }

  saveWebhook(): void {
    this.api
      .putReadingsWebhook({
        url: (this.webhook.url || '').trim() || null,
        interval_s: Number(this.webhook.interval_s),
        enabled: this.webhook.enabled,
      })
      .subscribe({
        next: (c) => {
          this.webhook = { url: c.url ?? '', interval_s: c.interval_s, enabled: c.enabled };
          this.flashWebhook('success', 'Saved.');
        },
        error: () => this.flashWebhook('danger', 'Could not save the webhook.'),
      });
  }

  testWebhook(): void {
    this.api.testReadingsWebhook().subscribe({
      next: (r) =>
        this.flashWebhook(
          r.sent ? 'success' : 'warning',
          r.sent ? 'Test POST sent.' : 'Nothing to send yet — no readings available.',
        ),
      error: (err) => this.flashWebhook('danger', err?.error?.detail || 'Test POST failed.'),
    });
  }

  private flashWebhook(cls: string, text: string): void {
    this.webhookMsg.set({ cls, text });
    setTimeout(() => this.webhookMsg.set(null), 4000);
  }

  /** Re-enumerate the host's serial ports (also the rescan button). */
  refreshPorts(): void {
    this.api.getSerialPorts().subscribe((res) => this.serialPorts.set(res.ports));
  }

  private loadProfiles(): void {
    this.api.getProfiles().subscribe((res) => this.profiles.set(res.profiles));
  }

  /** Probe the connection for the values currently in the Add-device form. */
  /** Build the transport-specific params block for create/test. */
  private deviceParams(): Record<string, unknown> {
    if (this.form.transport === 'solarman_v5') {
      return {
        host: this.form.host,
        serial: this.form.serial,
        port: Number(this.form.solarmanPort),
        slave_id: this.form.slaveId,
      };
    }
    return { port: this.form.port, slave_id: this.form.slaveId };
  }

  /** Whether the Test-connection button has enough to probe (per transport). */
  canTest(): boolean {
    if (!this.form.profile) return false;
    return this.form.transport === 'solarman_v5'
      ? !!(this.form.host && this.form.serial)
      : !!this.form.port;
  }

  testConnection(): void {
    this.testing.set(true);
    this.testResult.set(null);
    this.api
      .testDevice({
        transport: this.form.transport,
        profile: this.form.profile,
        params: this.deviceParams(),
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
    if (this.form.transport !== 'dummy') {
      body['profile'] = this.form.profile;
      body['params'] = this.deviceParams();
    }
    this.api.createDevice(body).subscribe({
      next: () => {
        this.form = { id: '', name: '', transport: 'dummy', profile: '', port: '', slaveId: 1, host: '', serial: '', solarmanPort: 8899 };
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
