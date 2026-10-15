// Service worker van de declaratietool.
// Bewust zuinig: pagina's en bijlagen komen altijd van de server en worden nooit bewaard,
// zodat er geen declaratie- of bankgegevens op de telefoon achterblijven.
// Alleen de offline-pagina, de opmaak en de iconen staan in de cache.
const CACHE = "declaratietool-v1";
const PRECACHE = [
  "/offline",
  "/static/style.css",
  "/static/icons/icon-192.png",
  "/static/icons/favicon-32.png",
];

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(CACHE).then((cache) => cache.addAll(PRECACHE)));
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (event) => {
  const request = event.request;
  if (request.method !== "GET" || new URL(request.url).origin !== self.location.origin) return;

  // Pagina's: altijd van de server; zonder verbinding de offline-pagina.
  if (request.mode === "navigate") {
    event.respondWith(fetch(request).catch(() => caches.match("/offline")));
    return;
  }

  // Opmaak en iconen: eerst de server (zo zie je na een update meteen de nieuwe versie),
  // zonder verbinding de bewaarde versie.
  if (PRECACHE.includes(new URL(request.url).pathname)) {
    event.respondWith(
      fetch(request)
        .then((response) => {
          if (response.ok) {
            const copy = response.clone();
            caches.open(CACHE).then((cache) => cache.put(request, copy));
          }
          return response;
        })
        .catch(() => caches.match(request))
    );
  }
});
