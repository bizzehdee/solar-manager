import { Component, OnInit, inject, signal } from '@angular/core';
import { RouterOutlet, RouterLink, RouterLinkActive } from '@angular/router';
import { DatePipe } from '@angular/common';

import { ThemeService } from './core/theme.service';
import { LiveService } from './core/live.service';
import { ApiService } from './core/api.service';
import { StatusPill } from './shared/status-pill';

// Fixed admin shell (plan.md §8): header / sidebar / footer; content is the only
// scroll region. Only this container subscribes to live data (smart/dumb split).
@Component({
  selector: 'app-root',
  imports: [RouterOutlet, RouterLink, RouterLinkActive, StatusPill, DatePipe],
  template: `
    <div [class.sidebar-collapsed]="!sidebarOpen()">
      <header class="app-header navbar navbar-expand bg-body-tertiary border-bottom fixed-top px-3">
        <button class="btn btn-sm btn-outline-secondary me-2" (click)="toggleSidebar()" aria-label="Toggle sidebar">
          <i class="bi bi-list"></i>
        </button>
        <span class="navbar-brand mb-0 h5"><i class="bi bi-sun text-warning"></i> Solar Manager</span>
        <div class="ms-auto d-flex align-items-center gap-3">
          <app-status-pill [status]="live.status()" />
          <button class="btn btn-sm btn-outline-secondary" (click)="theme.toggle()" aria-label="Toggle theme">
            <i class="bi" [class.bi-moon-stars]="theme.theme() === 'light'" [class.bi-sun]="theme.theme() === 'dark'"></i>
          </button>
        </div>
      </header>

      <nav class="app-sidebar p-2">
        <ul class="nav nav-pills flex-column gap-1">
          @for (item of nav; track item.path) {
            <li class="nav-item">
              <a class="nav-link d-flex align-items-center gap-2" [routerLink]="item.path" routerLinkActive="active">
                <i class="bi {{ item.icon }}"></i> {{ item.label }}
              </a>
            </li>
          }
        </ul>
      </nav>

      <main class="app-content">
        <router-outlet />
      </main>

      <footer class="app-footer d-flex align-items-center justify-content-between px-3 bg-body-tertiary border-top fixed-bottom text-secondary">
        <span>v{{ version() || '—' }}</span>
        <span>{{ now() | date: 'mediumTime' }}</span>
      </footer>
    </div>
  `,
})
export class App implements OnInit {
  readonly theme = inject(ThemeService);
  readonly live = inject(LiveService);
  private readonly api = inject(ApiService);

  readonly sidebarOpen = signal(true);
  readonly version = signal('');
  readonly now = signal(new Date());

  readonly nav = [
    { path: 'now', label: 'Now', icon: 'bi-speedometer2' },
    { path: 'history', label: 'History', icon: 'bi-graph-up' },
    { path: 'forecast', label: 'Forecast', icon: 'bi-cloud-sun' },
    { path: 'control', label: 'Control', icon: 'bi-sliders' },
    { path: 'settings', label: 'Settings', icon: 'bi-gear' },
  ];

  ngOnInit(): void {
    this.live.start();
    this.api.getHealth().subscribe({ next: (h) => this.version.set(h.version) });
    setInterval(() => this.now.set(new Date()), 1000);
  }

  toggleSidebar(): void {
    this.sidebarOpen.update((v) => !v);
  }
}
