/* 데일리 노트 폰 앱 - 오프라인 보관 (인터넷이 없어도 열리고, 쓴 것은 폰에 남았다가 나중에 보낸다). 글꼴은 fonts-v1 에 따로 오래 보관 */
var VERSION = "26.10.14-4";
var CACHE = "daily-note-v" + VERSION;
var CORE = ["./", "./index.html", "./cm.js", "./manifest.webmanifest",
            "./apple-touch-icon.png", "./icon-192.png", "./icon-512.png"];

self.addEventListener("install", function(e){
  e.waitUntil(
    caches.open(CACHE)
      .then(function(c){ return c.addAll(CORE.map(function(u){ return new Request(u, { cache:"reload" }); })); })
      .catch(function(){})
      .then(function(){ return self.skipWaiting(); })
  );
});

self.addEventListener("activate", function(e){
  e.waitUntil(
    caches.keys()
      .then(function(ks){ return Promise.all(ks.map(function(k){ return k === CACHE || k === "fonts-v1" ? null : caches.delete(k); })); })
      .then(function(){ return self.clients.claim(); })
  );
});

self.addEventListener("fetch", function(e){
  var req = e.request;
  if (req.method !== "GET" || req.url.indexOf("version.json") >= 0) return;
  var box = req.url.slice(-6) === ".woff2" ? "fonts-v1" : CACHE;
  e.respondWith(
    caches.match(req, { ignoreSearch:true }).then(function(hit){
      if (hit) return hit;
      return fetch(req).then(function(res){
        if (res.ok){ var copy = res.clone(); caches.open(box).then(function(c){ c.put(req, copy); }).catch(function(){}); }
        return res;
      }).catch(function(){ return caches.match("./index.html"); });
    })
  );
});
