// Minimal service worker: makes the app installable and lets the shell open offline.
// API calls are never cached.
const CACHE = 'agents-dialpad-shell-v3';
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
  if (e.request.method !== 'GET' || url.origin !== location.origin || url.pathname.startsWith('/api/') || url.pathname.startsWith('/push-action')) return;
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
  const options = {
    body: d.body || '',
    tag: d.tag || 'agents-dialpad',
    data: { url: d.url || '/', approval: d.approval },
    icon: '/icon-192.png',
    badge: '/icon-192.png',
  };
  if (d.approval) {
    options.requireInteraction = true;
    options.actions = d.approval.can_allow
      ? [{ action: 'allow', title: 'Allow' }, { action: 'deny', title: 'Deny' }]
      : [{ action: 'deny', title: 'Deny' }, { action: 'open', title: 'Open' }];
  }
  // Always show a notification: browsers (Safari especially) penalise silent pushes.
  e.waitUntil(self.registration.showNotification(d.title || 'agents-dialpad', options));
});

self.addEventListener('notificationclick', (e) => {
  const notif = e.notification;
  const data = notif.data || {};
  const approval = data.approval;
  const tag = notif.tag || 'agents-dialpad';

  if ((e.action === 'allow' || e.action === 'deny') && approval) {
    notif.close();
    e.waitUntil((async () => {
      const allow = (e.action === 'allow');
      try {
        const res = await fetch('/push-action', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            chat: approval.chat,
            req: approval.req,
            token: approval.token,
            allow: allow,
          }),
        });
        let msg = '';
        if (res.status === 200) {
          msg = allow ? 'Allowed' : 'Denied';
        } else if (res.status === 409) {
          msg = 'Already decided in the app';
        } else {
          msg = "Couldn't reach your computer. Open the app to decide.";
        }
        await self.registration.showNotification('agents-dialpad', {
          body: msg,
          tag: tag,
          icon: '/icon-192.png',
          badge: '/icon-192.png',
          data: { url: data.url || '/' },
        });
      } catch (err) {
        await self.registration.showNotification('agents-dialpad', {
          body: "Couldn't reach your computer. Open the app to decide.",
          tag: tag,
          icon: '/icon-192.png',
          badge: '/icon-192.png',
          data: { url: data.url || '/' },
        });
      }
    })());
    return;
  }

  notif.close();
  const url = new URL(data.url || '/', self.location.origin).href;
  e.waitUntil((async () => {
    const wins = await clients.matchAll({ type: 'window', includeUncontrolled: true });
    for (const w of wins) { if ('focus' in w) { try { await w.navigate(url); } catch { /* ignore */ } return w.focus(); } }
    return clients.openWindow(url);
  })());
});
