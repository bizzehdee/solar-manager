// SolarVolt service worker (plan.md §19 / T094) — self-hosted, no CDN.
// Goal: installable PWA that rides out brief network blips on the home LAN. Strategy:
//   • navigations  → network-first, fall back to the cached app shell when offline
//   • static GETs  → stale-while-revalidate (instant from cache, refreshed in the background)
//   • /api + /ws   → never cached (always live data)
// Registered only in production builds (see main.ts), so it can't interfere with ng serve.

const CACHE = 'solarvolt-v1';

self.addEventListener('install', (event) => {
  event.waitUntil(caches.open(CACHE).then((c) => c.add('/')));
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k)))),
  );
  self.clients.claim();
});

self.addEventListener('fetch', (event) => {
  const req = event.request;
  const url = new URL(req.url);
  if (req.method !== 'GET' || url.origin !== self.location.origin) return;
  if (url.pathname.startsWith('/api') || url.pathname.startsWith('/ws')) return; // live data, never cached

  if (req.mode === 'navigate') {
    event.respondWith(
      fetch(req)
        .then((res) => {
          caches.open(CACHE).then((c) => c.put('/', res.clone()));
          return res;
        })
        .catch(() => caches.match('/').then((r) => r || caches.match(req))),
    );
    return;
  }

  event.respondWith(
    caches.match(req).then((cached) => {
      const network = fetch(req)
        .then((res) => {
          if (res.ok) caches.open(CACHE).then((c) => c.put(req, res.clone()));
          return res;
        })
        .catch(() => cached);
      return cached || network;
    }),
  );
});
