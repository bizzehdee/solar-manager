# Locales

UI translations, one JSON file per locale. **`en-US.json` is the source of truth** — it
holds every translation key. Other locales may be partial; any missing key falls back to the
English string (see `app/core/translate.service.ts`), so an untranslated string degrades to
English rather than breaking.

Each file is:

```json
{
  "meta": { "id": "<locale-code>", "label": "<language name in that language>" },
  "strings": { "<key>": "<translated text>" }
}
```

## Adding a translated locale

Contributors translate via the **🌐 New locale / translation** issue (or a PR). To wire a new
locale `<code>.json` into the app, a maintainer does two things:

1. **Strings** — add `import xxJson from './<code>.json';` to `index.ts` and append it to
   `LOCALES`. This makes it appear in the Settings → locale dropdown and supplies its UI strings.
2. **Formatting data** — register Angular's locale data for date/number formatting in
   `src/app/app.config.ts` (`registerLocaleData(localeXx)` from `@angular/common/locales/<code>`).

`locales.spec.ts` guards that every locale's keys are a subset of `en-US` (no typo'd/orphan keys)
and that `en-US` covers them — keep it green when adding strings.
