import { Pipe, PipeTransform, inject } from '@angular/core';

import { TranslateService } from './translate.service';

// `{{ 'settings.devices.title' | translate }}` — resolves a UI-string key to the active
// locale. Pure: the locale is fixed per app instance (LOCALE_ID), so the result never
// changes once rendered, and a locale switch takes effect on reload (as for formatting).
@Pipe({ name: 'translate', pure: true })
export class TranslatePipe implements PipeTransform {
  private readonly t = inject(TranslateService);

  transform(key: string): string {
    return this.t.translate(key);
  }
}
