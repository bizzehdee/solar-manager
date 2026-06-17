import { Component, computed, input } from '@angular/core';

import { ConnStatus } from '../core/models';

// Presentational connection-status pill (plan.md §8). green=live, amber=polling fallback.
@Component({
  selector: 'app-status-pill',
  template: `<span class="badge rounded-pill" [class]="'text-bg-' + color()">
    <i class="bi" [class.bi-broadcast]="status() === 'live'"
       [class.bi-arrow-repeat]="status() === 'polling'"
       [class.bi-hourglass-split]="status() === 'connecting'"></i>
    {{ label() }}</span>`,
})
export class StatusPill {
  readonly status = input<ConnStatus>('connecting');

  readonly color = computed(() =>
    ({ live: 'success', polling: 'warning', connecting: 'secondary' })[this.status()],
  );
  readonly label = computed(() =>
    ({ live: 'Live', polling: 'Reconnecting', connecting: 'Connecting' })[this.status()],
  );
}
