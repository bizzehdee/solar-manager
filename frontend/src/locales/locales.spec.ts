import { LOCALES, SOURCE_LOCALE, findLocale } from './index';

// Integrity guard for the locale data files: contributors add/edit JSON, so this catches
// the common mistakes (typo'd or orphaned keys, mismatched meta.id, a broken source file).
describe('locale data files', () => {
  const source = findLocale(SOURCE_LOCALE);

  it('has a source-of-truth locale with strings', () => {
    expect(source).toBeDefined();
    expect(Object.keys(source!.strings).length).toBeGreaterThan(0);
  });

  it('gives every locale a meta.id that matches how it is looked up', () => {
    for (const loc of LOCALES) {
      expect(loc.meta.id).toBeTruthy();
      expect(loc.meta.label).toBeTruthy();
      expect(findLocale(loc.meta.id)).toBe(loc);
    }
  });

  it('uses no key that is missing from the en-US source (no orphans/typos)', () => {
    const sourceKeys = new Set(Object.keys(source!.strings));
    for (const loc of LOCALES) {
      for (const key of Object.keys(loc.strings)) {
        expect.soft(sourceKeys.has(key), `${loc.meta.id} has stray key "${key}"`).toBe(true);
      }
    }
  });

  it('has non-empty values for every translated string', () => {
    for (const loc of LOCALES) {
      for (const [key, value] of Object.entries(loc.strings)) {
        expect.soft(value.trim().length, `${loc.meta.id}:${key} is empty`).toBeGreaterThan(0);
      }
    }
  });
});
