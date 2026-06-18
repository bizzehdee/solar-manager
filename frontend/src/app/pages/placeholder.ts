import { Component } from '@angular/core';

// Placeholder pages for the remaining sidebar routes (plan.md §8). These land as real
// views in later phases: read-only settings display in Phase 5, schema-driven Control
// (edit/write) in Phase 6. History, Settings/Devices became real pages in Phase 2;
// Forecast in Phase 4. Kept tiny so the shell + routing are exercised now.

@Component({
  selector: 'app-control',
  template: `<h4 class="mb-3"><i class="bi bi-sliders"></i> Control</h4>
    <div class="alert alert-secondary">
      Read-only settings display arrives in Phase 5; schema-driven inverter control
      (edit/write) in Phase 6 (off by default).
    </div>`,
})
export class ControlPage {}
