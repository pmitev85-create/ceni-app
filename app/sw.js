// Офлайн работа: приложението се пази в кеша, цените – винаги първо от мрежата.
const KESH = "ceni-v4";
const OSNOVA = ["./", "index.html", "style.css", "app.js", "manifest.webmanifest", "icons/icon-192.png", "icons/icon-512.png"];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(KESH).then((c) => c.addAll(OSNOVA)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches.keys()
      .then((k) => Promise.all(k.filter((x) => x !== KESH).map((x) => caches.delete(x))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (e) => {
  const url = new URL(e.request.url);
  if (e.request.method !== "GET" || url.origin !== location.origin) return;
  // мрежа първо (за да има най-новите цени и версия), кеш – ако няма интернет
  e.respondWith(
    fetch(e.request)
      .then((r) => {
        const kopie = r.clone();
        caches.open(KESH).then((c) => c.put(e.request, kopie));
        return r;
      })
      .catch(() => caches.match(e.request, { ignoreSearch: true }))
  );
});
