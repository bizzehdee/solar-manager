import { TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting, HttpTestingController } from '@angular/common/http/testing';

import { PreferencesService } from './preferences.service';

describe('PreferencesService', () => {
  let http: HttpTestingController;
  let svc: PreferencesService;

  beforeEach(() => {
    localStorage.removeItem('solarvolt.locale');
    TestBed.configureTestingModule({
      providers: [provideHttpClient(), provideHttpClientTesting()],
    });
    http = TestBed.inject(HttpTestingController);
    svc = TestBed.inject(PreferencesService);
  });

  afterEach(() => http.verify());

  it('defaults to en-US and lists supported locales', () => {
    expect(svc.locale()).toBe('en-US');
    expect(svc.supported.map((l) => l.id)).toContain('en-GB');
  });

  it('load() syncs locale from the backend into the signal + localStorage', () => {
    svc.load();
    http.expectOne('/api/preferences').flush({ locale: 'de' });
    expect(svc.locale()).toBe('de');
    expect(localStorage.getItem('solarvolt.locale')).toBe('de');
  });

  it('save() stores locally and PUTs the preference', () => {
    const obs = svc.save('fr');
    expect(svc.locale()).toBe('fr');
    expect(localStorage.getItem('solarvolt.locale')).toBe('fr');
    obs.subscribe();
    const req = http.expectOne('/api/preferences');
    expect(req.request.body).toEqual({ locale: 'fr' });
    req.flush({ locale: 'fr' });
  });
});
