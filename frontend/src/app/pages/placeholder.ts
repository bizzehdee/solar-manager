import { Component } from '@angular/core';

// Placeholder pages for the remaining sidebar routes (plan.md §8). These land as real
// views in later phases: History (Phase 2), Forecast (Phase 4), Control (Phase 5),
// Settings/Devices (Phase 2). Kept tiny so the shell + routing are exercised now.

@Component({
  selector: 'app-history',
  template: `<h4 class="mb-3"><i class="bi bi-graph-up"></i> History</h4>
    <div class="alert alert-secondary">History &amp; charts arrive in Phase 2.</div>`,
})
export class HistoryPage {}

@Component({
  selector: 'app-forecast',
  template: `<h4 class="mb-3"><i class="bi bi-cloud-sun"></i> Forecast</h4>
    <div class="alert alert-secondary">Solar &amp; battery forecast arrives in Phase 4.</div>`,
})
export class ForecastPage {}

@Component({
  selector: 'app-control',
  template: `<h4 class="mb-3"><i class="bi bi-sliders"></i> Control</h4>
    <div class="alert alert-secondary">Schema-driven inverter control arrives in Phase 5 (off by default).</div>`,
})
export class ControlPage {}

@Component({
  selector: 'app-settings',
  template: `<h4 class="mb-3"><i class="bi bi-gear"></i> Settings</h4>
    <div class="alert alert-secondary">Devices, location, tariffs &amp; system spec arrive in Phase 2+.</div>`,
})
export class SettingsPage {}
