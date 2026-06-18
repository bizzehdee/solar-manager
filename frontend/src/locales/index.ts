// Locale registry (plan.md §19). Each locale is a JSON data file — `meta` (id + display
// label) plus a `strings` map of UI translation keys. Translators edit/add a JSON file and
// never touch TypeScript; adding a contributed locale = drop the file in this dir and add
// one import line below. Bundled at build (no CDN / no outbound requests — CLAUDE.md).
//
// en-US is the SOURCE locale: it must hold every key. Other locales may be partial; any
// missing key falls back to the en-US string (see TranslateService).

import deJson from './de.json';
import enGbJson from './en-GB.json';
import enUsJson from './en-US.json';
import esJson from './es.json';
import frJson from './fr.json';

export interface LocaleFile {
  meta: { id: string; label: string };
  strings: Record<string, string>;
}

/** The source-of-truth locale; the key set every contributed locale is checked against. */
export const SOURCE_LOCALE = 'en-US';

// English first, then the rest — matches the previously hard-coded order.
export const LOCALES: LocaleFile[] = [
  enUsJson,
  enGbJson,
  deJson,
  frJson,
  esJson,
] as LocaleFile[];

export function findLocale(id: string): LocaleFile | undefined {
  return LOCALES.find((l) => l.meta.id === id);
}
