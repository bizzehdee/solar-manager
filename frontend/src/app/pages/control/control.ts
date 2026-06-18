import { Component, computed, inject, OnInit, signal } from '@angular/core';
import { HttpErrorResponse } from '@angular/common/http';
import { DatePipe } from '@angular/common';

import { ApiService } from '../../core/api.service';
import {
  AuditEntry,
  DeviceConfig,
  DeviceSettingsResponse,
  SettingsField,
  SettingsSchemaResponse,
  SettingsSection,
} from '../../core/models';
import { SettingValue } from '../../shared/setting-value';
import { SettingInput } from '../../shared/setting-input';

// Control — Phase 5 read-only display + Phase 6 write-back (plan.md §12). Editing is gated:
// the backend reports `control_enabled` only when SOLARVOLT_ENABLE_CONTROL is on AND the
// device is writable; the edit controls render solely in that case. Every write goes through
// the §12 safety flow: schema validation → current→proposed diff → explicit confirm →
// server write → read-back verify (mismatch ⇒ rollback warning, never a silent success) →
// optimistic-concurrency etag (stale ⇒ reload, not clobber). One section (or one timer slot)
// is edited at a time, matching the backend's per-section PUT.
@Component({
  selector: 'app-control',
  imports: [SettingValue, SettingInput, DatePipe],
  template: `
    <h4 class="mb-1"><i class="bi bi-sliders"></i> Control</h4>
    @if (controlEnabled()) {
      <p class="small text-warning-emphasis mb-3">
        <i class="bi bi-pencil-square"></i> Editing is enabled — changes are written to the inverter and verified.
      </p>
    } @else {
      <p class="small text-secondary mb-3">
        Read-only — set <code>SOLARVOLT_ENABLE_CONTROL=true</code> to enable editing.
      </p>
    }

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

    @if (feedback(); as fb) {
      <div class="alert alert-{{ fb.cls }} d-flex align-items-start gap-2" role="alert">
        <i class="bi {{ fb.icon }} mt-1"></i>
        <div class="flex-grow-1">{{ fb.text }}</div>
        <button type="button" class="btn-close" aria-label="Dismiss" (click)="feedback.set(null)"></button>
      </div>
    }

    @if (loading()) {
      <div class="text-secondary"><span class="spinner-border spinner-border-sm"></span> Loading…</div>
    } @else if (!schema() || schema()?.supported === false) {
      <div class="alert alert-info mb-0"><i class="bi bi-info-circle"></i> This device exposes no settings.</div>
    } @else {
      @for (section of schema()!.sections; track section.key) {
        <div class="card mb-3">
          <div class="card-header d-flex align-items-center justify-content-between">
            <span>{{ section.label }}</span>
            <!-- Non-repeating section edit controls live in the header. -->
            @if (controlEnabled() && !section.repeating) {
              @if (isEditing(section.key, null)) {
                <span class="btn-group btn-group-sm">
                  <button class="btn btn-primary" (click)="review(section, null)">Review changes</button>
                  <button class="btn btn-outline-secondary" (click)="cancelEdit()">Cancel</button>
                </span>
              } @else {
                <button class="btn btn-sm btn-outline-primary" [disabled]="isBusy()" (click)="startEdit(section, null)">
                  <i class="bi bi-pencil"></i> Edit
                </button>
              }
            }
          </div>
          <div class="card-body p-0">
            @if (section.repeating) {
              <div class="table-responsive">
                <table class="table table-sm align-middle mb-0">
                  <thead>
                    <tr>
                      <th>#</th>
                      @for (f of section.fields; track f.key) { <th>{{ headerFor(f) }}</th> }
                      @if (controlEnabled()) { <th class="text-end">Actions</th> }
                    </tr>
                  </thead>
                  <tbody>
                    @for (row of rowsFor(section); track ri; let ri = $index) {
                      <tr [class.table-active]="isEditing(section.key, ri)">
                        <td class="text-secondary">Slot {{ ri + 1 }}</td>
                        @for (f of section.fields; track f.key) {
                          <td>
                            @if (isEditing(section.key, ri)) {
                              <app-setting-input
                                [field]="f"
                                [value]="draft()[f.key]"
                                (valueChange)="setDraft(f.key, $event)"
                              />
                            } @else {
                              <app-setting-value [field]="f" [value]="row[f.key]" />
                            }
                          </td>
                        }
                        @if (controlEnabled()) {
                          <td class="text-end text-nowrap">
                            @if (isEditing(section.key, ri)) {
                              <button class="btn btn-sm btn-primary me-1" (click)="review(section, ri)">Review</button>
                              <button class="btn btn-sm btn-outline-secondary" (click)="cancelEdit()">Cancel</button>
                            } @else {
                              <button
                                class="btn btn-sm btn-outline-primary"
                                [disabled]="isBusy()"
                                (click)="startEditRow(section, ri)"
                              >
                                <i class="bi bi-pencil"></i> Edit
                              </button>
                            }
                          </td>
                        }
                      </tr>
                    }
                  </tbody>
                </table>
              </div>
            } @else {
              <table class="table table-sm align-middle mb-0">
                <tbody>
                  @for (f of section.fields; track f.key) {
                    <tr>
                      <th class="w-50 fw-normal text-secondary">{{ headerFor(f) }}</th>
                      <td class="text-end">
                        @if (isEditing(section.key, null)) {
                          <app-setting-input
                            [field]="f"
                            [value]="draft()[f.key]"
                            (valueChange)="setDraft(f.key, $event)"
                          />
                        } @else {
                          <app-setting-value [field]="f" [value]="objFor(section)[f.key]" />
                        }
                      </td>
                    </tr>
                  }
                </tbody>
              </table>
            }
          </div>
        </div>
      }

      <!-- Recent writes (audit log, §12 rule 6). -->
      @if (controlEnabled() && audit().length) {
        <div class="card mb-3">
          <div class="card-header"><i class="bi bi-clock-history"></i> Recent changes</div>
          <ul class="list-group list-group-flush">
            @for (a of audit(); track $index) {
              <li class="list-group-item d-flex justify-content-between align-items-start gap-2">
                <div class="small">
                  <span class="text-secondary">{{ a.ts * 1000 | date: 'MMM d, HH:mm' }}</span>
                  — <strong>{{ a.section }}</strong>{{ a.slot !== null ? ' slot ' + (a.slot + 1) : '' }}:
                  {{ changeSummary(a) }}
                </div>
                <span class="badge text-bg-{{ a.result === 'ok' ? 'success' : 'danger' }}">{{ a.result }}</span>
              </li>
            }
          </ul>
        </div>
      }
    }

    <!-- Confirm dialog: current → proposed diff before any write (§12 rule 3). -->
    @if (confirm(); as c) {
      <div class="modal d-block" tabindex="-1" role="dialog" aria-modal="true">
        <div class="modal-dialog modal-dialog-centered">
          <div class="modal-content">
            <div class="modal-header">
              <h5 class="modal-title">Confirm changes</h5>
              <button type="button" class="btn-close" aria-label="Cancel" (click)="confirm.set(null)"></button>
            </div>
            <div class="modal-body">
              <p class="small text-secondary">
                Writing to <strong>{{ c.sectionLabel }}</strong>{{ c.index !== null ? ' · slot ' + (c.index + 1) : '' }}.
                Review the change{{ c.rows.length > 1 ? 's' : '' }}:
              </p>
              <table class="table table-sm align-middle mb-0">
                <tbody>
                  @for (r of c.rows; track r.field.key) {
                    <tr>
                      <th class="fw-normal text-secondary">{{ headerFor(r.field) }}</th>
                      <td class="text-end"><app-setting-value [field]="r.field" [value]="r.old" /></td>
                      <td class="text-center text-secondary"><i class="bi bi-arrow-right"></i></td>
                      <td><app-setting-value [field]="r.field" [value]="r.new" /></td>
                    </tr>
                  }
                </tbody>
              </table>
            </div>
            <div class="modal-footer">
              <button class="btn btn-outline-secondary" [disabled]="saving()" (click)="confirm.set(null)">Cancel</button>
              <button class="btn btn-primary" [disabled]="saving()" (click)="applyConfirmed()">
                @if (saving()) { <span class="spinner-border spinner-border-sm me-1"></span> }
                Apply &amp; verify
              </button>
            </div>
          </div>
        </div>
      </div>
      <div class="modal-backdrop show"></div>
    }
  `,
})
export class ControlPage implements OnInit {
  private readonly api = inject(ApiService);

  readonly devices = signal<DeviceConfig[]>([]);
  readonly settingsDevices = computed(() => this.devices().filter((d) => d.settings === true));

  readonly deviceId = signal<string | null>(null);
  readonly schema = signal<SettingsSchemaResponse | null>(null);
  readonly values = signal<DeviceSettingsResponse | null>(null);
  readonly loading = signal(false);

  // Edit state: which group is open, its working copy, the confirm dialog, save-in-flight,
  // a user-facing feedback banner, and the audit log.
  readonly edit = signal<{ section: string; index: number | null } | null>(null);
  readonly draft = signal<Record<string, unknown>>({});
  readonly confirm = signal<{
    section: string;
    sectionLabel: string;
    index: number | null;
    rows: { field: SettingsField; old: unknown; new: unknown }[];
  } | null>(null);
  readonly saving = signal(false);
  readonly feedback = signal<{ cls: string; icon: string; text: string } | null>(null);
  readonly audit = signal<AuditEntry[]>([]);

  readonly controlEnabled = computed(() => this.values()?.control_enabled === true);
  readonly isBusy = computed(() => this.edit() !== null || this.saving());

  ngOnInit(): void {
    this.api.getDevices().subscribe((res) => {
      this.devices.set(res.devices);
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
    this.cancelEdit();
    this.feedback.set(null);
    this.load(id);
  }

  private load(id: string): void {
    this.loading.set(true);
    let pending = 2;
    const done = () => {
      if (--pending === 0) this.loading.set(false);
    };
    this.api.getDeviceSettingsSchema(id).subscribe({
      next: (s) => (this.schema.set(s), done()),
      error: () => (this.schema.set(null), done()),
    });
    this.api.getDeviceSettings(id).subscribe({
      next: (v) => {
        this.values.set(v);
        if (v.control_enabled) this.loadAudit(id);
        done();
      },
      error: () => (this.values.set(null), done()),
    });
  }

  private loadAudit(id: string): void {
    this.api.getAudit(id).subscribe({ next: (r) => this.audit.set(r.entries), error: () => {} });
  }

  // --- editing ---
  startEdit(section: SettingsSection, index: number | null): void {
    this.feedback.set(null);
    this.edit.set({ section: section.key, index });
    this.draft.set({ ...this.groupValues(section.key, index) });
  }

  startEditRow(section: SettingsSection, index: number): void {
    this.startEdit(section, index);
  }

  cancelEdit(): void {
    this.edit.set(null);
    this.draft.set({});
    this.confirm.set(null);
  }

  isEditing(sectionKey: string, index: number | null): boolean {
    const e = this.edit();
    return e !== null && e.section === sectionKey && e.index === index;
  }

  setDraft(key: string, val: unknown): void {
    this.draft.update((d) => ({ ...d, [key]: val }));
  }

  /** Open the confirm dialog with the changed fields (current → proposed). No-op if nothing changed. */
  review(section: SettingsSection, index: number | null): void {
    const current = this.groupValues(section.key, index);
    const d = this.draft();
    const rows = section.fields
      .filter((f) => d[f.key] !== current[f.key])
      .map((f) => ({ field: f, old: current[f.key], new: d[f.key] }));
    if (rows.length === 0) {
      this.feedback.set({ cls: 'secondary', icon: 'bi-info-circle', text: 'No changes to apply.' });
      return;
    }
    this.confirm.set({ section: section.key, sectionLabel: section.label, index, rows });
  }

  applyConfirmed(): void {
    const c = this.confirm();
    const id = this.deviceId();
    if (!c || !id) return;
    const values = Object.fromEntries(c.rows.map((r) => [r.field.key, r.new]));
    this.saving.set(true);
    this.api.putDeviceSettings(id, { section: c.section, index: c.index, values }, this.values()?.etag).subscribe({
      next: (res) => {
        this.applyValues(id, res.etag, res.values);
        this.cancelEdit();
        this.feedback.set({ cls: 'success', icon: 'bi-check-circle', text: 'Settings written and verified.' });
        this.saving.set(false);
        this.loadAudit(id);
      },
      error: (err: HttpErrorResponse) => {
        this.handleWriteError(id, err);
        this.saving.set(false);
      },
    });
  }

  private handleWriteError(id: string, err: HttpErrorResponse): void {
    this.confirm.set(null);
    const body = err.error;
    if (err.status === 409) {
      // Read-back mismatch: the write didn't verify — surface as a rollback warning and
      // sync the UI to the device's actual state (§12 rule 4).
      this.applyValues(id, body?.etag, body?.values);
      this.cancelEdit();
      this.loadAudit(id); // a write was attempted — refresh the log (records the mismatch)
      const fields = (body?.mismatches ?? []).join(', ');
      this.feedback.set({
        cls: 'danger',
        icon: 'bi-exclamation-triangle',
        text: `Read-back verification failed for: ${fields || 'unknown fields'}. The change may not have applied — values reloaded from the device.`,
      });
    } else if (err.status === 412) {
      // Stale etag: someone/something changed the device since we read it. Reload, don't clobber.
      this.cancelEdit();
      this.load(id);
      this.feedback.set({
        cls: 'warning',
        icon: 'bi-arrow-clockwise',
        text: 'Settings changed since you opened them — reloaded. Review and try again.',
      });
    } else if (err.status === 422) {
      const errors: string[] = body?.detail?.errors ?? [];
      this.feedback.set({
        cls: 'danger',
        icon: 'bi-x-circle',
        text: `Validation failed: ${errors.join('; ') || 'invalid values'}.`,
      });
    } else if (err.status === 403) {
      this.feedback.set({ cls: 'secondary', icon: 'bi-lock', text: 'Control is disabled on this server.' });
    } else {
      this.feedback.set({ cls: 'danger', icon: 'bi-x-circle', text: 'Write failed — the device did not respond.' });
    }
  }

  private applyValues(id: string, etag: string | null | undefined, vals: Record<string, unknown> | undefined): void {
    if (vals === undefined) return;
    this.values.set({ device_id: id, supported: true, control_enabled: true, etag: etag ?? null, values: vals });
  }

  // --- value access helpers ---
  /** Current decoded values for a group (a non-repeating section object, or one timer slot). */
  private groupValues(sectionKey: string, index: number | null): Record<string, unknown> {
    const v = this.values()?.values?.[sectionKey];
    if (index !== null) {
      const arr = (Array.isArray(v) ? v : []) as Record<string, unknown>[];
      return arr[index] ?? {};
    }
    return (v && typeof v === 'object' && !Array.isArray(v) ? v : {}) as Record<string, unknown>;
  }

  objFor(section: SettingsSection): Record<string, unknown> {
    return this.groupValues(section.key, null);
  }

  rowsFor(section: SettingsSection): Record<string, unknown>[] {
    const v = this.values()?.values?.[section.key];
    return (Array.isArray(v) ? v : []) as Record<string, unknown>[];
  }

  headerFor(f: SettingsField): string {
    return f.unit ? `${f.label} (${f.unit})` : f.label;
  }

  /** One-line "field: old → new" summary for an audit row. */
  changeSummary(a: AuditEntry): string {
    return Object.entries(a.changes)
      .map(([k, v]) => `${k}: ${String(v.old)} → ${String(v.new)}`)
      .join(', ');
  }
}
