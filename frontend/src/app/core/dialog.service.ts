import { Injectable, signal } from '@angular/core';

// App-wide modal dialogs (replaces the native prompt()/confirm() — see <app-dialog>). A single
// host component renders the current request; callers await a Promise. Bootstrap-styled (bundled
// CSS, no Bootstrap JS).
export interface DialogState {
  kind: 'prompt' | 'confirm';
  title: string;
  label?: string; // prompt input label
  value?: string; // prompt initial value
  message?: string; // confirm body text
  confirmText?: string;
  danger?: boolean; // red confirm button (destructive actions)
}

@Injectable({ providedIn: 'root' })
export class DialogService {
  readonly state = signal<DialogState | null>(null);
  private resolver: ((v: string | boolean | null) => void) | null = null;

  /** Ask for a text value. Resolves to the trimmed string, or null if cancelled/blank. */
  prompt(opts: Omit<DialogState, 'kind'>): Promise<string | null> {
    return new Promise((res) => {
      this.resolver = res as (v: string | boolean | null) => void;
      this.state.set({ kind: 'prompt', value: '', confirmText: 'OK', ...opts });
    });
  }

  /** Ask for confirmation. Resolves true (confirmed) or false (cancelled). */
  confirm(opts: Omit<DialogState, 'kind'>): Promise<boolean> {
    return new Promise((res) => {
      this.resolver = res as (v: string | boolean | null) => void;
      this.state.set({ kind: 'confirm', confirmText: 'OK', ...opts });
    });
  }

  /** Called by the host to close the dialog with a result. */
  resolve(result: string | boolean | null): void {
    this.state.set(null);
    const r = this.resolver;
    this.resolver = null;
    r?.(result);
  }
}
