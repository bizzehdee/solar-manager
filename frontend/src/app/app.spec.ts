import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting, HttpTestingController } from '@angular/common/http/testing';

import { App } from './app';
import { routes } from './app.routes';

describe('App shell', () => {
  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [App],
      providers: [provideRouter(routes), provideHttpClient(), provideHttpClientTesting()],
    }).compileComponents();
  });

  it('creates the shell with brand + dashboards group + tools', () => {
    const fixture = TestBed.createComponent(App);
    fixture.detectChanges();
    const http = TestBed.inject(HttpTestingController);
    http.match('/api/health').forEach((r) =>
      r.flush({ version: '9.9', devices: [], poll_interval_s: 3, status: 'ok', control_enabled: false }),
    );
    // The sidebar lists the dashboards (built-ins first) it fetched on init.
    http.match('/api/dashboards').forEach((r) =>
      r.flush({ dashboards: [
        { id: 'now', name: 'Now', builtin: true, widgets: [] },
        { id: 'history', name: 'History', builtin: true, widgets: [] },
      ] }),
    );
    fixture.detectChanges();

    const el = fixture.nativeElement as HTMLElement;
    expect(el.querySelector('.navbar-brand')?.textContent).toContain('SolarVolt');
    const links = el.querySelectorAll('.app-sidebar .nav-link');
    const labels = Array.from(links).map((l) => l.textContent?.trim());
    expect(labels).toContain('Now');
    expect(labels).toContain('History');
    expect(labels).toContain('Settings');
    expect(labels.some((l) => l?.includes('New dashboard'))).toBe(true);
  });
});
