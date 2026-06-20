import { Component, HostListener, OnDestroy, OnInit, inject, signal } from '@angular/core';
import { Router, RouterOutlet, RouterLink, RouterLinkActive } from '@angular/router';
import { DatePipe } from '@angular/common';

import { ThemeService } from './core/theme.service';
import { LiveService } from './core/live.service';
import { ApiService } from './core/api.service';
import { DashboardsService } from './core/dashboards.service';
import { PreferencesService } from './core/preferences.service';
import { DashboardConfig } from './core/models';
import { downloadDashboard } from './core/dashboard-file';
import { StatusPill } from './shared/status-pill';

// Fixed admin shell (plan.md §8): header / sidebar / footer; content is the only
// scroll region. Only this container subscribes to live data (smart/dumb split).
@Component({
  selector: 'app-root',
  imports: [RouterOutlet, RouterLink, RouterLinkActive, StatusPill, DatePipe],
  template: `
    <div [class.sidebar-collapsed]="!sidebarOpen()" [class.sidebar-open]="sidebarOpen()">
      <header class="app-header navbar navbar-expand bg-body-tertiary border-bottom fixed-top px-3">
        <button class="btn btn-sm btn-outline-secondary me-2" (click)="toggleSidebar()" aria-label="Toggle sidebar">
          <i class="bi bi-list"></i>
        </button>
        <span class="navbar-brand mb-0 h5"><i class="bi bi-sun text-warning"></i> SolarVolt</span>
        <div class="ms-auto d-flex align-items-center gap-3">
          <app-status-pill [status]="live.status()" />
          <a class="btn btn-sm btn-outline-secondary position-relative" routerLink="alerts" aria-label="Alerts">
            <i class="bi bi-bell"></i>
            @if (alertCount() > 0) {
              <span class="position-absolute top-0 start-100 translate-middle badge rounded-pill text-bg-danger">
                {{ alertCount() }}<span class="visually-hidden">active alerts</span>
              </span>
            }
          </a>
          <button class="btn btn-sm btn-outline-secondary" (click)="theme.toggle()" aria-label="Toggle theme">
            <i class="bi" [class.bi-moon-stars]="theme.theme() === 'light'" [class.bi-sun]="theme.theme() === 'dark'"></i>
          </button>
        </div>
      </header>

      <!-- Mobile-only scrim behind the off-canvas sidebar; tap to dismiss. -->
      <div class="sidebar-backdrop" (click)="sidebarOpen.set(false)"></div>

      <nav class="app-sidebar p-2">
        <!-- Dashboards: built-ins (Now, History) then user dashboards, then "+ New" (L06/T_DB6). -->
        <ul class="nav nav-pills flex-column gap-1">
          @for (d of dashboards.dashboards(); track d.id) {
            <li class="nav-item d-flex align-items-center">
              <a class="nav-link flex-grow-1 d-flex align-items-center gap-2" [routerLink]="routeFor(d)"
                 routerLinkActive="active" (click)="onNavigate()">
                <i class="bi {{ iconFor(d) }}"></i> {{ d.name }}
              </a>
              @if (!d.builtin) {
                <div class="dashboard-menu position-relative">
                  <button class="btn btn-sm btn-link text-secondary px-1" (click)="toggleMenu(d.id, $event)"
                          [attr.aria-label]="'Actions for ' + d.name">
                    <i class="bi bi-three-dots"></i>
                  </button>
                  @if (openMenuId() === d.id) {
                    <div class="dropdown-menu show position-absolute end-0 mt-1">
                      <button class="dropdown-item" (click)="rename(d)">Rename</button>
                      <button class="dropdown-item" (click)="exportDashboard(d)">Export JSON</button>
                      <button class="dropdown-item text-danger" (click)="remove(d)">Delete</button>
                    </div>
                  }
                </div>
              }
            </li>
          }
          <li class="nav-item">
            <button class="nav-link d-flex align-items-center gap-2 w-100 border-0 bg-transparent text-start"
                    (click)="newDashboard()">
              <i class="bi bi-plus-lg"></i> New dashboard
            </button>
          </li>
        </ul>

        <hr class="my-2" />

        <ul class="nav nav-pills flex-column gap-1">
          @for (item of tools; track item.path) {
            <li class="nav-item">
              <a class="nav-link d-flex align-items-center gap-2" [routerLink]="item.path"
                 routerLinkActive="active" (click)="onNavigate()">
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
export class App implements OnInit, OnDestroy {
  readonly theme = inject(ThemeService);
  readonly live = inject(LiveService);
  readonly dashboards = inject(DashboardsService);
  private readonly api = inject(ApiService);
  private readonly prefs = inject(PreferencesService);
  private readonly router = inject(Router);

  // Open by default on desktop, closed on mobile (where the sidebar is an off-canvas
  // overlay). The hamburger toggles it; on mobile it slides in over a backdrop.
  readonly sidebarOpen = signal(isWideViewport());
  readonly version = signal('');
  readonly now = signal(new Date());
  readonly alertCount = signal(0); // active+unacked alerts, polled for the header bell badge
  readonly openMenuId = signal<string | null>(null); // which dashboard's ⋯ menu is open

  // Non-dashboard tools (the dashboards group above is dynamic).
  readonly tools = [
    { path: 'forecast', label: 'Forecast', icon: 'bi-cloud-sun' },
    { path: 'control', label: 'Control', icon: 'bi-sliders' },
    { path: 'automation', label: 'Automation', icon: 'bi-robot' },
    { path: 'alerts', label: 'Alerts', icon: 'bi-bell' },
    { path: 'settings', label: 'Settings', icon: 'bi-gear' },
  ];

  private timers: ReturnType<typeof setInterval>[] = [];

  ngOnInit(): void {
    this.live.start();
    this.dashboards.refresh();
    this.prefs.load(); // sync the saved locale from the backend (applies next reload)
    this.api.getHealth().subscribe({ next: (h) => this.version.set(h.version) });
    this.timers.push(setInterval(() => this.now.set(new Date()), 1000));
    // Poll the active-alert count for the header bell (the alert engine runs server-side).
    this.refreshAlertCount();
    this.timers.push(setInterval(() => this.refreshAlertCount(), 30000));
  }

  ngOnDestroy(): void {
    this.timers.forEach(clearInterval);
  }

  /** Built-ins keep their dedicated routes; user dashboards use the generic `/dashboard/:id`. */
  routeFor(d: DashboardConfig): string | string[] {
    if (d.id === 'now') return 'now';
    if (d.id === 'history') return 'history';
    return ['dashboard', d.id];
  }

  iconFor(d: DashboardConfig): string {
    if (d.id === 'now') return 'bi-speedometer2';
    if (d.id === 'history') return 'bi-graph-up';
    return 'bi-grid-1x2';
  }

  toggleMenu(id: string, e: Event): void {
    e.stopPropagation();
    this.openMenuId.update((cur) => (cur === id ? null : id));
  }

  /** Close any open ⋯ menu when clicking elsewhere. */
  @HostListener('document:click')
  closeMenu(): void {
    this.openMenuId.set(null);
  }

  newDashboard(): void {
    const name = this.askName('New dashboard name', '');
    if (!name) return;
    this.dashboards.create(name).subscribe((d) => {
      this.router.navigate(['dashboard', d.id]);
      this.onNavigate();
    });
  }

  rename(d: DashboardConfig): void {
    const name = this.askName('Rename dashboard', d.name);
    if (!name || name === d.name) return;
    this.dashboards.rename(d, name).subscribe();
  }

  exportDashboard(d: DashboardConfig): void {
    this.api.getDashboard(d.id).subscribe((cfg) => downloadDashboard(cfg));
  }

  remove(d: DashboardConfig): void {
    if (!this.confirmDelete(d.name)) return;
    this.dashboards.remove(d.id).subscribe(() => this.router.navigate(['now']));
  }

  // --- prompt/confirm seams (overridable in tests) ---
  askName(message: string, initial: string): string | null {
    const v = typeof prompt === 'function' ? prompt(message, initial) : null;
    return v && v.trim() ? v.trim() : null;
  }
  confirmDelete(name: string): boolean {
    return typeof confirm === 'function' ? confirm(`Delete dashboard "${name}"?`) : false;
  }

  private refreshAlertCount(): void {
    this.api.getAlerts(true, 1).subscribe({ next: (r) => this.alertCount.set(r.active_count) });
  }

  toggleSidebar(): void {
    this.sidebarOpen.update((v) => !v);
  }

  /** After tapping a nav item, dismiss the off-canvas sidebar on mobile (on desktop it
   *  stays pinned). */
  onNavigate(): void {
    if (!isWideViewport()) this.sidebarOpen.set(false);
  }
}

/** True on desktop-width viewports (matches the ≤768px sidebar media query in styles.scss).
 *  Guards `window` so it's safe under jsdom/SSR. */
function isWideViewport(): boolean {
  return typeof window === 'undefined' || window.innerWidth > 768;
}
