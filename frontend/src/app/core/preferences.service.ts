import { Injectable, inject, signal } from '@angular/core';

import { ApiService } from './api.service';
import { SUPPORTED_LOCALES, setStoredLocale, storedLocale } from './locale';

// Formatting preferences (plan.md §19 / T093). Holds the active locale (used at bootstrap
// for LOCALE_ID), syncs it from the backend so a new device inherits the choice, and saves
// changes back. Locale changes take effect on reload (LOCALE_ID is fixed per app instance).
@Injectable({ providedIn: 'root' })
export class PreferencesService {
  private readonly api = inject(ApiService);
  readonly supported = SUPPORTED_LOCALES;
  readonly locale = signal(storedLocale());

  /** Pull the stored preference from the backend and cache it locally (applies next reload). */
  load(): void {
    this.api.getPreferences().subscribe({
      next: (p) => {
        if (p.locale) {
          this.locale.set(p.locale);
          setStoredLocale(p.locale);
        }
      },
      error: () => {},
    });
  }

  /** Persist a locale locally + on the backend. Returns the PUT observable so the caller
   *  can reload once it succeeds (to re-bootstrap with the new LOCALE_ID). */
  save(locale: string) {
    setStoredLocale(locale);
    this.locale.set(locale);
    return this.api.putPreferences({ locale });
  }
}
