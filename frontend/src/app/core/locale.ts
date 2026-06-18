// Shared locale helpers (plan.md §19 / T093). The active locale is persisted in
// localStorage so LOCALE_ID can be resolved synchronously at bootstrap (before any HTTP),
// then synced from the backend by PreferencesService for cross-device consistency.

import { LOCALES } from '../../locales';

const KEY = 'solarvolt.locale';
export const DEFAULT_LOCALE = 'en-US';

/** The selectable locales, derived from the bundled locale data files (locales/*.json).
 *  Adding a translated locale means adding a JSON file, not editing this list. Each must
 *  also have its Angular formatting data registered in app.config (registerLocaleData). */
export const SUPPORTED_LOCALES: { id: string; label: string }[] = LOCALES.map((l) => l.meta);

export function storedLocale(): string {
  try {
    return localStorage.getItem(KEY) || DEFAULT_LOCALE;
  } catch {
    return DEFAULT_LOCALE;
  }
}

export function setStoredLocale(locale: string): void {
  try {
    localStorage.setItem(KEY, locale);
  } catch {
    /* ignore (private mode / no storage) */
  }
}
