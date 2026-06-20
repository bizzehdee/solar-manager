import { Routes } from '@angular/router';

// Lazy standalone pages. Now is the default view (plan.md §8).
export const routes: Routes = [
  { path: '', pathMatch: 'full', redirectTo: 'now' },
  { path: 'now', loadComponent: () => import('./pages/now/now').then((m) => m.NowPage), title: 'Now' },
  { path: 'history', loadComponent: () => import('./pages/history/history').then((m) => m.HistoryPage), title: 'History' },
  { path: 'forecast', loadComponent: () => import('./pages/forecast/forecast').then((m) => m.ForecastPage), title: 'Forecast' },
  { path: 'control', loadComponent: () => import('./pages/control/control').then((m) => m.ControlPage), title: 'Control' },
  { path: 'automation', loadComponent: () => import('./pages/automation/automation').then((m) => m.AutomationPage), title: 'Automation' },
  { path: 'alerts', loadComponent: () => import('./pages/alerts/alerts').then((m) => m.AlertsPage), title: 'Alerts' },
  { path: 'settings', loadComponent: () => import('./pages/settings/settings').then((m) => m.SettingsPage), title: 'Settings' },
  // User dashboards (L06): the Now/History built-ins keep dedicated routes; everything else is generic.
  { path: 'dashboard/:id', loadComponent: () => import('./pages/dashboard/dashboard').then((m) => m.DashboardPage), title: 'Dashboard' },
  // Diagnostics moved into Settings (its own tab); keep the old path as a redirect for bookmarks.
  { path: 'diagnostics', redirectTo: 'settings' },
  { path: '**', redirectTo: 'now' },
];
