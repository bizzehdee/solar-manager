import { isDevMode } from '@angular/core';
import { bootstrapApplication } from '@angular/platform-browser';
import { appConfig } from './app/app.config';
import { App } from './app/app';

bootstrapApplication(App, appConfig).catch((err) => console.error(err));

// Register the self-hosted service worker for offline/installable behaviour (T094).
// Production only — in dev (ng serve) it would fight HMR and serve stale assets.
if (!isDevMode() && 'serviceWorker' in navigator) {
  navigator.serviceWorker.register('sw.js').catch(() => {});
}
