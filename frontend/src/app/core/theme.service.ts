import { Injectable, signal } from '@angular/core';

// Bootstrap 5.3 native color modes (plan.md §8): sets data-bs-theme on <html>,
// persists the choice, and defaults to the OS preference.
export type Theme = 'light' | 'dark';
const STORAGE_KEY = 'solar-manager.theme';

@Injectable({ providedIn: 'root' })
export class ThemeService {
  readonly theme = signal<Theme>(this.initial());

  constructor() {
    this.apply(this.theme());
  }

  toggle(): void {
    this.set(this.theme() === 'dark' ? 'light' : 'dark');
  }

  set(theme: Theme): void {
    this.theme.set(theme);
    this.apply(theme);
    try {
      localStorage.setItem(STORAGE_KEY, theme);
    } catch {
      /* storage unavailable — non-fatal */
    }
  }

  private apply(theme: Theme): void {
    document.documentElement.setAttribute('data-bs-theme', theme);
  }

  private initial(): Theme {
    try {
      const saved = localStorage.getItem(STORAGE_KEY) as Theme | null;
      if (saved === 'light' || saved === 'dark') return saved;
    } catch {
      /* ignore */
    }
    return window.matchMedia?.('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
  }
}
