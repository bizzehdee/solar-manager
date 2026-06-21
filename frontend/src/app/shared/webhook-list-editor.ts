import { Component, computed, effect, input, output, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';

import { WebhookEndpoint } from '../core/models';

// Dynamic add/edit/remove list of custom webhook endpoints (L15), shared by both egress paths:
// alert/notification webhooks and outbound readings webhooks. Each endpoint has a label, URL,
// method, content-type, headers, an optional payload template (with preset buttons + a
// placeholder hint) and an enabled switch; readings endpoints also carry their own interval.
// Presentational + self-contained: it works on a local copy and emits the full list on Save, or a
// single endpoint on Test (the parent owns the API calls). An empty template ⇒ the default body.

interface Row extends WebhookEndpoint {
  headersText: string; // transient "Key: Value" lines, parsed back to `headers` on save
}

function headersToText(headers: Record<string, string>): string {
  return Object.entries(headers || {}).map(([k, v]) => `${k}: ${v}`).join('\n');
}

function textToHeaders(text: string): Record<string, string> {
  const out: Record<string, string> = {};
  for (const line of (text || '').split('\n')) {
    const i = line.indexOf(':');
    if (i <= 0) continue;
    const k = line.slice(0, i).trim();
    const v = line.slice(i + 1).trim();
    if (k) out[k] = v;
  }
  return out;
}

@Component({
  selector: 'app-webhook-list-editor',
  imports: [FormsModule],
  template: `
    @if (rows().length === 0) {
      <p class="small text-secondary mb-2">No webhooks yet.</p>
    }
    @for (row of rows(); track $index) {
      <div class="border rounded p-2 mb-2">
        <div class="row g-2 align-items-end">
          <div class="col-12 col-md-5">
            <label class="form-label small text-secondary mb-0">Label</label>
            <input class="form-control form-control-sm" [(ngModel)]="row.label" [name]="'whLabel' + $index"
                   placeholder="e.g. Node-RED" aria-label="Webhook label" />
          </div>
          <div class="col-12 col-md-5">
            <label class="form-label small text-secondary mb-0">URL</label>
            <input class="form-control form-control-sm" [(ngModel)]="row.url" [name]="'whUrl' + $index"
                   placeholder="endpoint URL" aria-label="Webhook URL" />
          </div>
          <div class="col-12 col-md-2 d-flex align-items-center gap-2 justify-content-md-end">
            <div class="form-check form-switch mb-0">
              <input class="form-check-input" type="checkbox" role="switch" [(ngModel)]="row.enabled"
                     [name]="'whEn' + $index" [id]="'whEn' + $index" aria-label="Webhook enabled" />
              <label class="form-check-label small" [for]="'whEn' + $index">On</label>
            </div>
            <button type="button" class="btn btn-sm btn-outline-danger" (click)="remove($index)"
                    aria-label="Remove webhook"><i class="bi bi-trash"></i></button>
          </div>

          <div class="col-6 col-md-3">
            <label class="form-label small text-secondary mb-0">Method</label>
            <select class="form-select form-select-sm" [(ngModel)]="row.method" [name]="'whMethod' + $index">
              <option value="POST">POST</option>
              <option value="PUT">PUT</option>
              <option value="GET">GET</option>
            </select>
          </div>
          <div class="col-6 col-md-4">
            <label class="form-label small text-secondary mb-0">Content-Type</label>
            <input class="form-control form-control-sm" [(ngModel)]="row.content_type" [name]="'whCt' + $index"
                   placeholder="application/json" aria-label="Content type" />
          </div>
          @if (readings()) {
            <div class="col-6 col-md-3">
              <label class="form-label small text-secondary mb-0">Interval (s)</label>
              <input type="number" min="5" class="form-control form-control-sm" [(ngModel)]="row.interval_s"
                     [name]="'whInt' + $index" aria-label="Interval seconds" />
            </div>
          }

          <div class="col-12">
            <label class="form-label small text-secondary mb-0">Headers (one <code>Key: Value</code> per line)</label>
            <textarea rows="2" class="form-control form-control-sm font-monospace" [(ngModel)]="row.headersText"
                      [name]="'whHdr' + $index" placeholder="Authorization: Bearer …" aria-label="Headers"></textarea>
          </div>

          <div class="col-12">
            <div class="d-flex flex-wrap align-items-center gap-2 mb-1">
              <label class="form-label small text-secondary mb-0">Payload template</label>
              <div class="btn-group btn-group-sm" role="group" aria-label="Payload presets">
                @for (p of presets(); track p.label) {
                  <button type="button" class="btn btn-outline-secondary" (click)="applyPreset($index, p)">{{ p.label }}</button>
                }
              </div>
            </div>
            <textarea rows="2" class="form-control form-control-sm font-monospace" [(ngModel)]="row.payload_template"
                      [name]="'whTmpl' + $index" placeholder="Empty = default body (the full JSON)"
                      aria-label="Payload template"></textarea>
            <p class="small text-secondary mt-1 mb-0">
              Placeholders: {{ placeholderHint() }}. Values are JSON-escaped; a bad template falls back to the default body.
            </p>
          </div>

          <div class="col-12">
            <button type="button" class="btn btn-sm btn-outline-secondary" (click)="test.emit(toEndpoint(row))"
                    [disabled]="!row.url">
              <i class="bi bi-send"></i> Test
            </button>
          </div>
        </div>
      </div>
    }

    <div class="d-flex gap-2 mt-2">
      <button type="button" class="btn btn-sm btn-outline-primary" (click)="add()">
        <i class="bi bi-plus-lg"></i> Add webhook
      </button>
      <button type="button" class="btn btn-sm btn-primary" (click)="emitSave()">
        <i class="bi bi-save"></i> Save
      </button>
    </div>
  `,
})
export class WebhookListEditor {
  readonly endpoints = input<WebhookEndpoint[]>([]);
  readonly readings = input(false); // show the per-endpoint interval field
  readonly placeholders = input<string[]>([]);

  readonly save = output<WebhookEndpoint[]>();
  readonly test = output<WebhookEndpoint>();

  readonly rows = signal<Row[]>([]);

  readonly placeholderHint = computed(() => {
    const p = this.placeholders();
    return p.length ? p.map((k) => `{${k}}`).join(', ') : '{…}';
  });

  // Sensible payload presets per egress type (Slack/Discord want a specific JSON shape).
  readonly presets = computed<{ label: string; template: string; content_type?: string }[]>(() => {
    const msg = this.readings() ? 'PV {pv_power_w} W' : '{name}: {message}';
    return [
      { label: 'Default', template: '' },
      { label: 'Slack', template: `{"text": "${msg}"}` },
      { label: 'Discord', template: `{"content": "${msg}"}` },
    ];
  });

  constructor() {
    // Re-seed the working rows whenever the parent supplies a new list (load / after save).
    effect(() => {
      this.rows.set(this.endpoints().map((e) => ({ ...e, headersText: headersToText(e.headers) })));
    });
  }

  add(): void {
    this.rows.update((rows) => [
      ...rows,
      {
        id: '', label: '', url: '', method: 'POST', headers: {}, headersText: '',
        content_type: 'application/json', payload_template: '', enabled: false,
        ...(this.readings() ? { interval_s: 60 } : {}),
      },
    ]);
  }

  remove(i: number): void {
    this.rows.update((rows) => rows.filter((_, idx) => idx !== i));
  }

  applyPreset(i: number, preset: { template: string; content_type?: string }): void {
    this.rows.update((rows) =>
      rows.map((r, idx) => (idx === i ? { ...r, payload_template: preset.template } : r)),
    );
  }

  /** Strip the transient headersText and parse it back into the headers map. */
  toEndpoint(row: Row): WebhookEndpoint {
    const { headersText, ...rest } = row;
    return { ...rest, headers: textToHeaders(headersText) };
  }

  emitSave(): void {
    this.save.emit(this.rows().map((r) => this.toEndpoint(r)));
  }
}
