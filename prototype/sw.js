/* SuperPlump SW v4 — network-first app shell; offline cache is fallback only. */
const C = "plump-v4";
self.addEventListener("install", e => { e.waitUntil(caches.open(C).then(c => c.addAll(["/app"]))); self.skipWaiting(); });
self.addEventListener("activate", e => e.waitUntil(caches.keys().then(keys => Promise.all(keys.filter(k => k !== C && k.startsWith('plump-')).map(k => caches.delete(k)))).then(() => clients.claim())));
self.addEventListener("fetch", e => {
  const u = new URL(e.request.url);
  if (u.pathname.startsWith("/v1") || u.pathname === "/health") return;          // API: luôn network
  if (u.pathname === "/app" || u.pathname === "/") {
    e.respondWith(fetch(e.request, { cache: "no-store" })
      .then(r => { const cp = r.clone(); caches.open(C).then(c => c.put("/app", cp)); return r; })
      .catch(() => caches.match("/app")));
    return;
  }
  e.respondWith(fetch(e.request).catch(() => caches.match(e.request)));
});
