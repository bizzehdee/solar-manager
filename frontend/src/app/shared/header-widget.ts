import { Component, input } from '@angular/core';

// Section header for dashboards (L06): a full-width label used to group/name the widgets below it.
// Purely presentational — heading text + optional icon/colour, no live data. Defaults to a 12×1 cell
// (see the widget registry). Multiple headers can be placed on one dashboard to split it into named
// sections.
@Component({
  selector: 'app-header-widget',
  template: `<div class="d-flex align-items-center gap-2 h-100 px-1 border-bottom">
    @if (icon()) { <i class="bi {{ icon() }} fs-5 text-{{ role() }}"></i> }
    <span class="fs-5 fw-semibold text-truncate text-{{ role() }}">{{ text() }}</span>
  </div>`,
})
export class HeaderWidget {
  readonly text = input('Section');
  readonly icon = input('');
  readonly role = input('body');
}
