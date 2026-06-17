import { Injectable, inject } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';

import { Health, Snapshot } from './models';

// REST surface (plan.md §7). Same-origin in production; proxied to the backend in dev.
@Injectable({ providedIn: 'root' })
export class ApiService {
  private http = inject(HttpClient);

  getHealth(): Observable<Health> {
    return this.http.get<Health>('/api/health');
  }

  getLive(): Observable<Snapshot> {
    return this.http.get<Snapshot>('/api/live');
  }
}
