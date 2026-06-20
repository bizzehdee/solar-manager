import { TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting, HttpTestingController } from '@angular/common/http/testing';

import { DashboardsService, slugify } from './dashboards.service';

describe('slugify', () => {
  it('makes a URL-safe slug', () => {
    expect(slugify('Garage Loads!')).toBe('garage-loads');
    expect(slugify('  Solar / Battery  ')).toBe('solar-battery');
  });
});

describe('DashboardsService', () => {
  let svc: DashboardsService;
  let http: HttpTestingController;

  beforeEach(() => {
    TestBed.configureTestingModule({ providers: [provideHttpClient(), provideHttpClientTesting()] });
    svc = TestBed.inject(DashboardsService);
    http = TestBed.inject(HttpTestingController);
  });

  function loadList(): void {
    svc.refresh();
    http.expectOne('/api/dashboards').flush({
      dashboards: [
        { id: 'now', name: 'Now', builtin: true, widgets: [] },
        { id: 'history', name: 'History', builtin: true, widgets: [] },
        { id: 'garage', name: 'Garage', builtin: false, widgets: [] },
      ],
    });
  }

  it('splits builtins from user dashboards', () => {
    loadList();
    expect(svc.builtins().map((d) => d.id)).toEqual(['now', 'history']);
    expect(svc.userDashboards().map((d) => d.id)).toEqual(['garage']);
  });

  it('uniqueId avoids collisions with existing ids', () => {
    loadList();
    expect(svc.uniqueId('Loft')).toBe('loft');
    expect(svc.uniqueId('Garage')).toBe('garage-2'); // 'garage' taken
  });

  it('uniqueName suffixes a colliding name', () => {
    loadList();
    expect(svc.uniqueName('Loft')).toBe('Loft');
    expect(svc.uniqueName('Garage')).toBe('Garage (2)'); // 'Garage' taken
  });

  it('create PUTs a blank dashboard under a slug id and refreshes', () => {
    loadList();
    svc.create('My Loft').subscribe();
    const put = http.expectOne((r) => r.method === 'PUT' && r.url === '/api/dashboards/my-loft');
    expect(put.request.body).toEqual({ name: 'My Loft', widgets: [] });
    put.flush({ id: 'my-loft', name: 'My Loft', builtin: false, widgets: [] });
    http.expectOne('/api/dashboards').flush({ dashboards: [] }); // refresh after create
  });

  it('remove DELETEs and refreshes', () => {
    loadList();
    svc.remove('garage').subscribe();
    http.expectOne((r) => r.method === 'DELETE' && r.url === '/api/dashboards/garage').flush(null);
    http.expectOne('/api/dashboards').flush({ dashboards: [] });
  });
});
