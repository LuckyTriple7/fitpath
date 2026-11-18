/* FitPath Service Worker: App-Hülle offline, Push */
const VERSION = "fp-v4";
const SHELL = ["/", "/app.js", "/styles.css", "/manifest.webmanifest", "/icons/icon-192.png", "/icons/icon-512.png"];

self.addEventListener("install", e => {
  e.waitUntil(caches.open(VERSION).then(c => c.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", e => {
  e.waitUntil(caches.keys().then(keys => Promise.all(keys.filter(k => k !== VERSION).map(k => caches.delete(k))))
    .then(() => self.clients.claim()));
});

self.addEventListener("fetch", e => {
  const url = new URL(e.request.url);
  if (e.request.method !== "GET" || url.origin !== location.origin) return;
  // API und Anmeldung nie aus dem Cache (die App merkt sich den letzten Zustand selbst)
  if (url.pathname.startsWith("/api/") || url.pathname.startsWith("/auth/")) return;
  // Netz zuerst, damit Updates sofort ankommen; offline aus dem Cache
  e.respondWith(
    fetch(e.request).then(resp => {
      if (resp.ok && SHELL.includes(url.pathname)) {
        const copy = resp.clone();
        caches.open(VERSION).then(c => c.put(e.request, copy));
      }
      return resp;
    }).catch(() => caches.match(e.request).then(r => r || caches.match("/")))
  );
});

self.addEventListener("push", e => {
  let data = { title: "FitPath", body: "", url: "/" };
  try { data = { ...data, ...e.data.json() }; } catch (_) { /* Text */ }
  e.waitUntil(self.registration.showNotification(data.title, {
    body: data.body,
    icon: "/icons/icon-192.png",
    badge: "/icons/badge-96.png",
    tag: data.tag || "fitpath",
    renotify: true,
    data: { url: data.url || "/" },
    vibrate: [80, 40, 80],
  }));
});

self.addEventListener("notificationclick", e => {
  e.notification.close();
  const target = (e.notification.data && e.notification.data.url) || "/";
  e.waitUntil(self.clients.matchAll({ type: "window", includeUncontrolled: true }).then(list => {
    for (const c of list) {
      if (new URL(c.url).origin === location.origin) { c.navigate(target); return c.focus(); }
    }
    return self.clients.openWindow(target);
  }));
});
