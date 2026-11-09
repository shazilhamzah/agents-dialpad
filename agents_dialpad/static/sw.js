// Minimal service worker: makes the app installable and lets the shell open offline.
// API calls are never cached.
const CACHE = 'agents-dialpad-shell-v2';
const SHELL = ['/', '/style.css', '/markdown.js', '/app.js', '/manifest.webmanifest', '/icon-192.png'];

self.addEventListener('install', (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting()));
});
self.addEventListener('activate', (e) => {
  e.waitUntil(caches.keys().then((ks) => Promise.all(ks.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
    .then(() => self.clients.claim()));
});
self.addEventListener('fetch', (e) => {
  const url = new URL(e.request.url);
  if (e.request.method !== 'GET' || url.origin !== location.origin || url.pathname.startsWith('/api/')) return;
  // network first, fall back to cache
  e.respondWith(
    fetch(e.request).then((r) => {
      const copy = r.clone(); caches.open(CACHE).then((c) => c.put(e.request, copy)); return r;
    }).catch(() => caches.match(e.request))
  );
});

self.addEventListener('push', (e) => {
  let d = {};
  try { d = e.data ? e.data.json() : {}; } catch { /* ignore */ }
  // Always show a notification: browsers (Safari especially) penalise silent pushes.
  e.waitUntil(self.registration.showNotification(d.title || 'agents-dialpad', {
    body: d.body || '', tag: d.tag || 'agents-dialpad', data: { url: d.url || '/' }, icon: '/icon-192.png', badge: '/icon-192.png',
  }));
});

self.addEventListener('notificationclick', (e) => {
  e.notification.close();
  const url = new URL((e.notification.data && e.notification.data.url) || '/', self.location.origin).href;
  e.waitUntil((async () => {
    const wins = await clients.matchAll({ type: 'window', includeUncontrolled: true });
    for (const w of wins) { if ('focus' in w) { try { await w.navigate(url); } catch { /* ignore */ } return w.focus(); } }
    return clients.openWindow(url);
  })());
});
