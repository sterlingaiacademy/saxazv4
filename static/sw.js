// SAXAZ Progressive Web App Service Worker
const CACHE_NAME = 'saxaz-pwa-v2';
const PRECACHE_ASSETS = [
  '/static/css/app.css?v=11',
  '/static/images/pwa-icon-192.png?v=2',
  '/static/images/pwa-icon-512.png?v=2'
];

self.addEventListener('install', (event) => {
  self.skipWaiting();
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.addAll(PRECACHE_ASSETS)).catch(() => {})
  );
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(
        keys.filter((k) => k !== CACHE_NAME).map((k) => caches.delete(k))
      )
    ).then(() => self.clients.claim())
  );
});

// Network-first strategy so dynamic exam/tutor data is always fresh,
// while satisfying browser PWA installability criteria.
self.addEventListener('fetch', (event) => {
  if (event.request.method !== 'GET') return;
  event.respondWith(
    fetch(event.request).catch(() => caches.match(event.request))
  );
});
