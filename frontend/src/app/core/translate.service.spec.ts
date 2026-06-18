import { LOCALE_ID } from '@angular/core';
import { TestBed } from '@angular/core/testing';

import { TranslateService } from './translate.service';
import { TranslatePipe } from './translate.pipe';

function serviceFor(localeId: string): TranslateService {
  TestBed.configureTestingModule({ providers: [{ provide: LOCALE_ID, useValue: localeId }] });
  return TestBed.inject(TranslateService);
}

describe('TranslateService', () => {
  it('translates a key to the active locale', () => {
    expect(serviceFor('de').translate('settings.devices.title')).toBe('Einstellungen — Geräte');
  });

  it('uses English for the source locale', () => {
    expect(serviceFor('en-US').translate('settings.devices.title')).toBe('Settings — Devices');
  });

  it('falls back to the en-US source for an unknown locale', () => {
    // 'xx' isn't a shipped locale -> strings default to the source map.
    expect(serviceFor('xx').translate('settings.devices.add')).toBe('Add device');
  });

  it('returns the key itself when no translation exists anywhere', () => {
    expect(serviceFor('de').translate('does.not.exist')).toBe('does.not.exist');
  });
});

describe('TranslatePipe', () => {
  it('delegates to the service', () => {
    TestBed.configureTestingModule({ providers: [{ provide: LOCALE_ID, useValue: 'fr' }] });
    const pipe = TestBed.runInInjectionContext(() => new TranslatePipe());
    expect(pipe.transform('settings.devices.testConnection')).toBe('Tester la connexion');
  });
});
