import { Component } from '@angular/core';

// Placeholder pages for the remaining sidebar routes (plan.md §8). These land as real
// views in later phases: Control (Phase 5). History, Settings/Devices became real pages
// in Phase 2; Forecast in Phase 4. Kept tiny so the shell + routing are exercised now.

@Component({
  selector: 'app-control',
  template: `<h4 class="mb-3"><i class="bi bi-sliders"></i> Control</h4>
    <div class="alert alert-secondary">Schema-driven inverter control arrives in Phase 5 (off by default).</div>`,
})
export class ControlPage {}
