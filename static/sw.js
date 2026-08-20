// Nexa ERP — service worker
// Intentionally does NOT cache anything. This app is data-driven
// (live bookings, invoices, stock) — serving stale cached responses
// would be actively wrong. This file exists only so Chrome/Edge treat
// the site as installable (a registered SW is a PWA install requirement).

self.addEventListener('install', (event) => {
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil(self.clients.claim());
});

// Pass every request straight to the network, no caching layer.
self.addEventListener('fetch', (event) => {
  event.respondWith(fetch(event.request));
});
