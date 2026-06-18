// Shared locale helpers (plan.md §19 / T093). The active locale is persisted in
// localStorage so LOCALE_ID can be resolved synchronously at bootstrap (before any HTTP),
// then synced from the backend by PreferencesService for cross-device consistency.

const KEY = 'solarvolt.locale';
export const DEFAULT_LOCALE = 'en-US';

/** Locales we ship formatting data for (registerLocaleData in app.config). English first. */
export const SUPPORTED_LOCALES: { id: string; label: string }[] = [
  { id: 'en-US', label: 'English (US)' },
  { id: 'en-GB', label: 'English (UK)' },
  { id: 'de', label: 'Deutsch' },
  { id: 'fr', label: 'Français' },
  { id: 'es', label: 'Español' },
];

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
