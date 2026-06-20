import { Component, effect, inject } from '@angular/core';
import { FormsModule } from '@angular/forms';

import { DialogService } from '../core/dialog.service';

// Single modal host for app-wide prompts/confirmations (DialogService). Rendered once in the app
// shell. Bootstrap modal markup with bundled CSS — `.modal.d-block` + a `.modal-backdrop` show it
// without Bootstrap's JS.
@Component({
  selector: 'app-dialog',
  imports: [FormsModule],
  template: `
    @if (svc.state(); as s) {
      <div class="modal d-block" tabindex="-1" role="dialog" (keydown.escape)="cancel()">
        <div class="modal-dialog modal-dialog-centered">
          <div class="modal-content">
            <div class="modal-header">
              <h5 class="modal-title">{{ s.title }}</h5>
              <button type="button" class="btn-close" aria-label="Close" (click)="cancel()"></button>
            </div>
            <div class="modal-body">
              @if (s.kind === 'prompt') {
                @if (s.label) { <label class="form-label" for="dlg-input">{{ s.label }}</label> }
                <input id="dlg-input" class="form-control" [(ngModel)]="value" autofocus
                       (keyup.enter)="ok()" />
              } @else {
                <p class="mb-0">{{ s.message }}</p>
              }
            </div>
            <div class="modal-footer">
              <button type="button" class="btn btn-outline-secondary" (click)="cancel()">Cancel</button>
              <button type="button" class="btn" [class]="s.danger ? 'btn-danger' : 'btn-primary'" (click)="ok()">
                {{ s.confirmText }}
              </button>
            </div>
          </div>
        </div>
      </div>
      <div class="modal-backdrop show"></div>
    }
  `,
})
export class DialogHost {
  readonly svc = inject(DialogService);
  value = '';

  constructor() {
    // Seed the input each time a prompt opens.
    effect(() => {
      const s = this.svc.state();
      if (s?.kind === 'prompt') this.value = s.value ?? '';
    });
  }

  ok(): void {
    const s = this.svc.state();
    if (!s) return;
    if (s.kind === 'prompt') {
      const v = this.value.trim();
      this.svc.resolve(v || null);
    } else {
      this.svc.resolve(true);
    }
  }

  cancel(): void {
    const s = this.svc.state();
    this.svc.resolve(s?.kind === 'prompt' ? null : false);
  }
}
