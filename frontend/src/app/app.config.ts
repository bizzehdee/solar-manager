import { ApplicationConfig, LOCALE_ID, provideBrowserGlobalErrorListeners } from '@angular/core';
import { provideRouter } from '@angular/router';
import { provideHttpClient, withFetch } from '@angular/common/http';
import { registerLocaleData } from '@angular/common';
import localeEnGb from '@angular/common/locales/en-GB';
import localeDe from '@angular/common/locales/de';
import localeFr from '@angular/common/locales/fr';
import localeEs from '@angular/common/locales/es';
import { provideCharts, withDefaultRegisterables } from 'ng2-charts';

import { routes } from './app.routes';
import { storedLocale } from './core/locale';

// Localization (T093): bundle (no CDN) the formatting data for the supported locales and
// resolve LOCALE_ID synchronously from localStorage at bootstrap. en-US is Angular's default.
registerLocaleData(localeEnGb);
registerLocaleData(localeDe);
registerLocaleData(localeFr);
registerLocaleData(localeEs);

export const appConfig: ApplicationConfig = {
  providers: [
    provideBrowserGlobalErrorListeners(),
    provideRouter(routes),
    provideHttpClient(withFetch()),
    provideCharts(withDefaultRegisterables()),
    { provide: LOCALE_ID, useFactory: storedLocale },
  ],
};
