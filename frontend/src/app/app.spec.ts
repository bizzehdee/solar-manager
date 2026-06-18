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

  it('creates the shell with brand + nav', () => {
    const fixture = TestBed.createComponent(App);
    fixture.detectChanges();
    const el = fixture.nativeElement as HTMLElement;
    // health request fired by ngOnInit
    TestBed.inject(HttpTestingController)
      .match('/api/health')
      .forEach((r) => r.flush({ version: '9.9', devices: [], poll_interval_s: 3, status: 'ok', control_enabled: false }));
    expect(el.querySelector('.navbar-brand')?.textContent).toContain('SolarVolt');
    expect(el.querySelectorAll('.app-sidebar .nav-link').length).toBe(5);
  });
});
