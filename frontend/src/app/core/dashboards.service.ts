import { Injectable, computed, inject, signal } from '@angular/core';
import { Observable, tap } from 'rxjs';

import { ApiService } from './api.service';
import { DashboardConfig } from './models';

// Shared dashboard catalogue (L06 / T_DB6): the single source the sidebar switcher and the
// Settings › Dashboards page read from. Holds the list as a signal and wraps the create/rename/
// delete CRUD so both views stay in sync after a change.
@Injectable({ providedIn: 'root' })
export class DashboardsService {
  private readonly api = inject(ApiService);

  readonly dashboards = signal<DashboardConfig[]>([]);
  readonly builtins = computed(() => this.dashboards().filter((d) => d.builtin));
  readonly userDashboards = computed(() => this.dashboards().filter((d) => !d.builtin));

  refresh(): void {
    this.api.getDashboards().subscribe({ next: (r) => this.dashboards.set(r.dashboards) });
  }

  /** Create a blank 12-column user dashboard from a name. The id is a unique slug of the name. */
  create(name: string): Observable<DashboardConfig> {
    const id = this.uniqueId(name);
    return this.api
      .putDashboard(id, { name: name.trim(), widgets: [] })
      .pipe(tap(() => this.refresh()));
  }

  rename(d: DashboardConfig, name: string): Observable<DashboardConfig> {
    return this.api
      .putDashboard(d.id, { name: name.trim(), widgets: d.widgets })
      .pipe(tap(() => this.refresh()));
  }

  remove(id: string): Observable<void> {
    return this.api.deleteDashboard(id).pipe(tap(() => this.refresh()));
  }

  /** A URL-safe slug of `name`, made unique against the current ids with a -2/-3… suffix. */
  uniqueId(name: string): string {
    const base = slugify(name) || 'dashboard';
    const taken = new Set(this.dashboards().map((d) => d.id));
    if (!taken.has(base)) return base;
    let n = 2;
    while (taken.has(`${base}-${n}`)) n++;
    return `${base}-${n}`;
  }
}

export function slugify(name: string): string {
  return name
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '');
}
