// SAXAZ V4 Studio Progressive Web App Service Worker
const CACHE_NAME = 'saxaz-v4-studio-v541';
const PRECACHE_ASSETS = [
  '/static/css/app.css?v=250',
  '/static/css/v2-studio.css?v=540',
  '/static/css/saxaz-fun.css?v=540',
  '/static/css/sx3.css?v=540',
  '/static/css/saxaz-ext.css?v=540',
  '/static/css/saxaz-match.css?v=2',
  '/static/js/saxaz-player.js?v=515',
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

self.addEventListener('fetch', (event) => {
  if (event.request.method !== 'GET') return;
  event.respondWith(
    fetch(event.request).catch(() => caches.match(event.request))
  );
});
