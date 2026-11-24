/* Alfalqi PDF app-shell service worker.
   Cache public UI fonts for offline use; never cache API responses, OAuth tokens,
   user documents, or Drive content. */
const CACHE_PREFIX = "alfalqi-pdf-";
const CACHE_VERSION = "shell-v4";
const CACHE_NAME = CACHE_PREFIX + CACHE_VERSION;
const APP_SHELL = [
  "./",
  "./index.html",
  "./config.js",
  "./experience.css",
  "./manifest.webmanifest",
  "./icon-192.png",
  "./icon-512.png",
  "./privacy.html"
];

self.addEventListener("install", event => {
  event.waitUntil((async () => {
    const cache = await caches.open(CACHE_NAME);
    await Promise.all(APP_SHELL.map(async path => {
      const url = new URL(path, self.registration.scope);
      try {
        const response = await fetch(new Request(url, { cache: "reload" }));
        if (response.ok) await cache.put(url, response);
      } catch (_) {
        // A failed optional shell resource must not block app installation.
      }
    }));
    await self.skipWaiting();
  })());
});

self.addEventListener("activate", event => {
  event.waitUntil((async () => {
    const names = await caches.keys();
    await Promise.all(names.filter(name => name.startsWith(CACHE_PREFIX) && name !== CACHE_NAME)
      .map(name => caches.delete(name)));
    await self.clients.claim();
  })());
});

function isCacheableExternalAsset(url, request) {
  if (url.hostname === "cdnjs.cloudflare.com") {
    return request.destination === "script" &&
      (url.pathname === "/ajax/libs/pdf.js/3.11.174/pdf.min.js" ||
       url.pathname === "/ajax/libs/pdf-lib/1.17.1/pdf-lib.min.js");
  }
  if (url.hostname === "fonts.googleapis.com") return request.destination === "style";
  if (url.hostname === "fonts.gstatic.com") return request.destination === "font";
  return false;
}

async function cachedExternalAsset(request) {
  const cache = await caches.open(CACHE_NAME);
  const cached = await cache.match(request);
  const refresh = fetch(request).then(response => {
    if (response && (response.ok || response.type === "opaque")) {
      cache.put(request, response.clone()).catch(() => {});
    }
    return response;
  }).catch(() => null);
  if (cached) {
    refresh.catch(() => {});
    return cached;
  }
  return (await refresh) || Response.error();
}

async function localAsset(request, url) {
  const cache = await caches.open(CACHE_NAME);
  if (request.mode === "navigate") {
    try {
      const response = await fetch(request);
      if (response.ok) cache.put(new URL("./index.html", self.registration.scope), response.clone()).catch(() => {});
      return response;
    } catch (_) {
      return (await cache.match(new URL("./index.html", self.registration.scope))) ||
        (await cache.match(new URL("./", self.registration.scope))) || Response.error();
    }
  }
  const cached = await cache.match(request);
  if (cached) return cached;
  try {
    const response = await fetch(request);
    if (response.ok && url.origin === self.location.origin &&
        url.pathname.startsWith(new URL(self.registration.scope).pathname)) {
      cache.put(request, response.clone()).catch(() => {});
    }
    return response;
  } catch (_) {
    return Response.error();
  }
}

self.addEventListener("fetch", event => {
  const request = event.request;
  if (request.method !== "GET") return;
  const url = new URL(request.url);

  // API calls are always live and are never stored by this service worker.
  if (url.origin === self.location.origin && /\/api(?:\/|$)/.test(url.pathname)) return;

  if (url.origin === self.location.origin) {
    if (!url.pathname.startsWith(new URL(self.registration.scope).pathname)) return;
    event.respondWith(localAsset(request, url));
    return;
  }

  // Only cache the exact, non-sensitive public libraries and web fonts used by the UI.
  if (isCacheableExternalAsset(url, request)) {
    event.respondWith(cachedExternalAsset(request));
  }
});
