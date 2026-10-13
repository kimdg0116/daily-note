/**
 * 데일리 노트 동기화 서버 — 폰 앱과 맥(옵시디언 볼트)이 같은 데일리 노트를 쓰게 하는 우체통. 전달만 하고 보관하지 않는다.
 * 노트의 원본은 맥 볼트, 사본은 폰 안(IndexedDB)에 전부 있다. 여기는 오가는 것만 잠깐 머문다.
 *
 *  맥 → 폰: 맥에서 바뀐 노트를 상자에 넣고(노트마다 b:<날짜>, 목록 bi = 날짜→[rev, 크기]), 폰이 rev 로 받아 간다. 상자가 차면(300KB) 오래된 것부터 버리고
 *           floor 를 올린다 → 그보다 오래 안 들른 폰은 stale 을 받고 처음부터 다시 받는다.
 *  처음·다시 받기: 폰이 want 를 걸면 맥이 모든 노트를 날짜순으로 몇 번에 나눠 상자에 넣는다
 *           (폰이 앞 묶음을 받은 걸 확인하고 다음 묶음).
 *  폰 → 맥: 폰에서 고친 칸은 받은 편지함(ob)에 모였다가 맥이 가져가 볼트에 쓰고 받았다고 알린다(done).
 *           맥이 꺼져 있어도 ob 에 남는다.
 * 저장은 Script Properties (gzip + base64, 8000자 조각) 뿐이라 따로 권한이 필요 없다.
 * 연결 코드는 Secret.js 의 CODE (git 제외, clasp 로만 올라감).
 *
 * 폰 → {code, op:'get', since}              → {rev, docs:{날짜:노트}, stale?, want?, dates?, mind?, wait:{날짜:칸 수}, macAt}
 * 폰 → {code, op:'want'}                    → {ok}       모든 노트 다시 받기 (처음 연결할 때)
 * 폰 → {code, op:'edit', date, fm, sec, t}  → {ok}       fm/sec = {키: {v: 새 값, b: 폰이 본 값}}
 * 맥 → {code, op:'mac', put, keep?, done, resync?, dates?, mind?} → {ob, want}
 *        resync = {to: 이번 묶음 마지막 날짜, done: 끝인지}, done = [[날짜, 'fm'|'sec', 키, t]]
 *
 * 반영: cd sync && ~/Desktop/app/dosimetrist-calendar-server/tools/node_modules/.bin/clasp push -f
 *       && …/clasp redeploy <배포 ID>   (배포 ID 는 server.py·index.html 의 SYNC_URL, URL 유지)
 */
const CH = 8000, BOX = 300000;                               // 상자 한도 (전체 저장 한도 500KB 중)
let ALL, W, DEL;                                             // 요청마다: 다 읽어 두고, 쓸 것·지울 것을 모아 한 번에

function doPost(e) {
  let q;
  try { q = JSON.parse(e.postData.contents); } catch (x) { return out_({ err: 'bad' }); }
  const cache = CacheService.getScriptCache(), bad = +(cache.get('bad') || 0);
  if (bad >= 30) return out_({ err: 'busy' });              // 틀린 코드가 몰리면 10분 쉰다
  if (q.code !== CODE) { cache.put('bad', String(bad + 1), 600); return out_({ err: 'code' }); }
  if (!OPS[q.op]) return out_({ err: 'bad' });
  const lock = LockService.getScriptLock();
  lock.waitLock(25000);
  try {
    const p = PropertiesService.getScriptProperties();
    ALL = p.getProperties(); W = {}; DEL = Object.keys(ALL).filter(k => /^(d:|idx#|sheet$)/.test(k));   // 예전 방식(노트 보관)의 흔적은 지운다
    const r = OPS[q.op](q);
    if (Object.keys(W).length) p.setProperties(W);
    DEL.forEach(k => p.deleteProperty(k));
    return out_(r);
  } finally { lock.releaseLock(); }
}

const pending_ = o => Object.keys(o.fm || {}).length + Object.keys(o.sec || {}).length;

const OPS = {
  get(q) {
    const bi = getJ_('bi') || {}, meta = getJ_('meta') || {}, ob = getJ_('ob') || {}, since = +q.since || 0, rev = +ALL.rev || 0;
    const r = { rev, docs: {}, wait: {}, macAt: meta.macAt || 0 };
    if (since && (meta.floor || 0) > since) r.stale = true;   // 그사이 상자에서 버린 노트가 있다 → 처음부터 다시
    for (const d in bi) if (bi[d][0] > since) r.docs[d] = getJ_('b:' + d);
    for (const d in ob) r.wait[d] = pending_(ob[d]);
    if ((meta.mrev || 0) > since) { r.dates = meta.dates || []; r.mind = meta.mind || []; }
    const want = getJ_('want');
    if (want) {
      want.seen = rev;                                        // 폰이 지금까지 넣은 걸 다 받았다
      if (want.done && want.seen >= want.sent) setJ_('want', null);
      else { setJ_('want', want); r.want = true; }
    }
    return r;
  },

  want() {
    setJ_('want', { from: '', sent: 0, seen: 0, done: false });
    return { ok: true };
  },

  edit(q) {
    if (!/^\d{4}-\d{2}-\d{2}$/.test(q.date)) return { err: 'bad' };
    const ob = getJ_('ob') || {}, o = ob[q.date] || (ob[q.date] = { fm: {}, sec: {} });
    for (const part of ['fm', 'sec']) for (const k in (q[part] || {})) {
      const e = q[part][k], prev = o[part][k];
      o[part][k] = { v: e.v, t: +q.t || Date.now(), b: prev ? prev.b : e.b };   // 폰이 본 값은 처음 고칠 때 것
    }
    setJ_('ob', ob);
    return { ok: true };
  },

  mac(q) {
    const ob = getJ_('ob') || {}, bi = getJ_('bi') || {}, meta = getJ_('meta') || {}, put = q.put || {};
    let rev = +ALL.rev || 0, want = getJ_('want');
    for (const [d, part, k, t] of q.done || []) {           // 맥이 볼트에 쓴 것 (그 사이 폰이 또 고쳤으면 남긴다)
      const e = ob[d] && ob[d][part] && ob[d][part][k];
      if (e && e.t === t) delete ob[d][part][k];
      if (ob[d] && !pending_(ob[d])) delete ob[d];
    }
    if (Object.keys(put).length || q.dates || q.mind) rev++;
    for (const d in put) {
      const o = ob[d];
      if (o) for (const part of ['fm', 'sec']) for (const k in o[part]) put[d][part][k] = o[part][k].v;   // 아직 볼트에 안 쓴 폰 수정은 위에 얹는다
      bi[d] = [rev, setJ_('b:' + d, put[d])];
    }
    if (q.resync && want) { want.from = q.resync.to; want.sent = rev; want.done = !!q.resync.done; setJ_('want', want); }
    if (q.dates) { meta.dates = q.dates; meta.mrev = rev; }
    if (q.mind) { meta.mind = q.mind; meta.mrev = rev; }
    meta.macAt = Date.now();
    setJ_('ob', ob);
    if (Object.keys(put).length) { fit_(bi, meta); setJ_('bi', bi); }
    setJ_('meta', meta);
    W.rev = String(rev);
    return { ob, want };
  },
};

function fit_(bi, meta) {                                     // 상자가 넘치면 오래된 것부터 버린다
  const order = Object.keys(bi).sort((a, b) => bi[a][0] - bi[b][0]);
  let total = order.reduce((n, d) => n + bi[d][1], 0);
  while (total > BOX && order.length > 1) {
    const d = order.shift();
    meta.floor = Math.max(meta.floor || 0, bi[d][0]); total -= bi[d][1];
    setJ_('b:' + d, null); delete bi[d];
  }
}

function out_(o) { return ContentService.createTextOutput(JSON.stringify(o)).setMimeType(ContentService.MimeType.JSON); }
const gz_ = v => Utilities.base64Encode(Utilities.gzip(Utilities.newBlob(JSON.stringify(v))).getBytes());

function getJ_(k) {
  const n = +ALL[k + '#n'] || 0;
  if (!n) return null;
  let s = '';
  for (let i = 0; i < n; i++) s += ALL[k + '#' + i];
  return JSON.parse(Utilities.ungzip(Utilities.newBlob(Utilities.base64Decode(s), 'application/x-gzip')).getDataAsString());
}

function setJ_(k, v) {                                       // v 가 null 이면 지운다. 저장한 크기(글자 수)를 돌려준다
  const old = +ALL[k + '#n'] || 0;
  let n = 0, s = '';
  if (v != null) {
    s = gz_(v);
    n = Math.ceil(s.length / CH);
    for (let i = 0; i < n; i++) W[k + '#' + i] = s.slice(i * CH, (i + 1) * CH);
    W[k + '#n'] = String(n);
  } else if (old) DEL.push(k + '#n');
  for (let i = n; i < old; i++) DEL.push(k + '#' + i);
  ALL[k + '#n'] = String(n);
  for (const key in W) ALL[key] = W[key];
  return s.length;
}
