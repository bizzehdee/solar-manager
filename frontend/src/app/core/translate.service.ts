import { Injectable, LOCALE_ID, inject } from '@angular/core';

import { SOURCE_LOCALE, findLocale } from '../../locales';

// Runtime UI-string translation (plan.md §19 — "strings externalized even if only English
// ships first"). Strings come from the bundled locale data files (locales/*.json); the
// active locale is fixed per app instance (LOCALE_ID, resolved at bootstrap), so lookups
// are a constant map — a missing key falls back to the en-US source string, then the key
// itself, so an untranslated screen degrades to English rather than breaking.
@Injectable({ providedIn: 'root' })
export class TranslateService {
  private readonly localeId = inject(LOCALE_ID);
  private readonly strings: Record<string, string>;
  private readonly source: Record<string, string>;

  constructor() {
    this.source = findLocale(SOURCE_LOCALE)?.strings ?? {};
    this.strings = findLocale(this.localeId)?.strings ?? this.source;
  }

  /** Translate a key to the active locale, falling back to en-US then the key itself. */
  translate(key: string): string {
    return this.strings[key] ?? this.source[key] ?? key;
  }
}
