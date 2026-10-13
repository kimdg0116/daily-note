/**
 * 데일리 노트 동기화 서버 — 폰 앱과 맥(옵시디언 볼트)이 같은 데일리 노트를 쓰게 하는 우체통.
 * 맥 server.py 가 최근 노트(35일 전 ~ 7일 뒤)를 올리고(mac), 폰은 받아 보고(get) 고친 칸을 보낸다(edit).
 * 폰에서 고친 칸은 받은 편지함(ob)에 모였다가 맥이 가져가 볼트에 쓰고 받았다고 알린다(done).
 * 맥이 꺼져 있어도 폰 수정은 여기 남고, 폰에서 다시 열면 고친 대로 보인다.
 * 저장은 Script Properties (gzip + base64, 8000자 조각). 연결 코드는 Secret.js 의 CODE (git 제외, clasp 로만 올라감).
 *
 * 폰 → {code, op:'get', since}                       → {rev, docs:{날짜:노트}, dates?, mind?, wait:{날짜:칸 수}, macAt}
 * 폰 → {code, op:'edit', date, fm, sec, t}            → {rev}      fm/sec = {키: {v: 새 값, b: 폰이 본 값}}
 * 맥 → {code, op:'mac', put, keep, done, dates?, mind?} → {ob}      done = [[날짜, 'fm'|'sec', 키, t]]
 *
 * 반영: cd sync && ~/Desktop/app/dosimetrist-calendar-server/tools/node_modules/.bin/clasp push -f
 *       && …/clasp redeploy <배포 ID>   (배포 ID 는 server.py·index.html 의 SYNC_URL, URL 유지)
 */
const CH = 8000;                                             // Script Properties 값 하나는 9KB 까지
let ALL, W, DEL;                                             // 요청마다: 다 읽어 두고, 쓸 것·지울 것을 모아 한 번에

function doPost(e) {
  let q;
  try { q = JSON.parse(e.postData.contents); } catch (x) { return out_({ err: 'bad' }); }
  const cache = CacheService.getScriptCache(), bad = +(cache.get('bad') || 0);
  if (bad >= 30) return out_({ err: 'busy' });              // 틀린 코드가 몰리면 10분 쉰다
  if (q.code !== CODE) { cache.put('bad', String(bad + 1), 600); return out_({ err: 'code' }); }
  if (!OPS[q.op]) return out_({ err: 'bad' });
  const lock = LockService.getScriptLock();
  lock.waitLock(20000);
  try {
    const p = PropertiesService.getScriptProperties();
    ALL = p.getProperties(); W = {}; DEL = [];
    const r = OPS[q.op](q);
    if (Object.keys(W).length) p.setProperties(W);
    DEL.forEach(k => p.deleteProperty(k));
    return out_(r);
  } finally { lock.releaseLock(); }
}

const blank_ = d => ({ date: d, exists: false, fm: {}, sec: { tomorrow: '', today: '', journal: '' }, quote: { state: 'new' }, author: null });
const pending_ = o => Object.keys(o.fm || {}).length + Object.keys(o.sec || {}).length;

const OPS = {
  get(q) {
    const idx = getJ_('idx') || {}, meta = getJ_('meta') || {}, ob = getJ_('ob') || {}, since = +q.since || 0, docs = {}, wait = {};
    for (const d in idx) if (idx[d] > since) docs[d] = getJ_('d:' + d);
    for (const d in ob) wait[d] = pending_(ob[d]);
    const r = { rev: +ALL.rev || 0, docs, wait, macAt: meta.macAt || 0 };
    if ((meta.mrev || 0) > since) { r.dates = meta.dates || []; r.mind = meta.mind || []; }
    return r;
  },

  edit(q) {
    if (!/^\d{4}-\d{2}-\d{2}$/.test(q.date)) return { err: 'bad' };
    const ob = getJ_('ob') || {}, idx = getJ_('idx') || {}, o = ob[q.date] || (ob[q.date] = { fm: {}, sec: {} });
    const doc = getJ_('d:' + q.date) || blank_(q.date), rev = (+ALL.rev || 0) + 1;
    for (const part of ['fm', 'sec']) for (const k in (q[part] || {})) {
      const e = q[part][k], prev = o[part][k];
      o[part][k] = { v: e.v, t: +q.t || Date.now(), b: prev ? prev.b : e.b };   // 폰이 본 값은 처음 고칠 때 것
      doc[part][k] = e.v;
    }
    idx[q.date] = rev;
    setJ_('ob', ob); setJ_('d:' + q.date, doc); setJ_('idx', idx); W.rev = String(rev);
    return { rev };
  },

  mac(q) {
    const ob = getJ_('ob') || {}, idx = getJ_('idx') || {}, meta = getJ_('meta') || {}, rev = (+ALL.rev || 0) + 1;
    let touched = false;
    for (const [d, part, k, t] of q.done || []) {           // 맥이 볼트에 쓴 것 (그 사이 폰이 또 고쳤으면 남긴다)
      const e = ob[d] && ob[d][part] && ob[d][part][k];
      if (e && e.t === t) delete ob[d][part][k];
      if (ob[d] && !pending_(ob[d])) delete ob[d];
    }
    for (const d in q.put || {}) {
      const doc = q.put[d], o = ob[d];
      if (o) for (const part of ['fm', 'sec']) for (const k in o[part]) doc[part][k] = o[part][k].v;   // 아직 볼트에 안 쓴 폰 수정은 위에 얹는다
      setJ_('d:' + d, doc); idx[d] = rev; touched = true;
    }
    if (q.keep) for (const d in idx) if (q.keep.indexOf(d) < 0 && !ob[d] && !(d in (q.put || {}))) { setJ_('d:' + d, null); delete idx[d]; }
    if (q.dates) { meta.dates = q.dates; meta.mrev = rev; touched = true; }
    if (q.mind) { meta.mind = q.mind; meta.mrev = rev; touched = true; }
    meta.macAt = Date.now();
    setJ_('ob', ob); setJ_('idx', idx); setJ_('meta', meta);
    if (touched) W.rev = String(rev);
    return { ob };
  },
};

function out_(o) { return ContentService.createTextOutput(JSON.stringify(o)).setMimeType(ContentService.MimeType.JSON); }

function getJ_(k) {
  const n = +ALL[k + '#n'] || 0;
  if (!n) return null;
  let s = '';
  for (let i = 0; i < n; i++) s += ALL[k + '#' + i];
  return JSON.parse(Utilities.ungzip(Utilities.newBlob(Utilities.base64Decode(s), 'application/x-gzip')).getDataAsString());
}

function setJ_(k, v) {                                       // v 가 null 이면 지운다
  const old = +ALL[k + '#n'] || 0;
  let n = 0;
  if (v != null) {
    const s = Utilities.base64Encode(Utilities.gzip(Utilities.newBlob(JSON.stringify(v))).getBytes());
    n = Math.ceil(s.length / CH);
    for (let i = 0; i < n; i++) W[k + '#' + i] = s.slice(i * CH, (i + 1) * CH);
    W[k + '#n'] = String(n);
  } else if (old) DEL.push(k + '#n');
  for (let i = n; i < old; i++) DEL.push(k + '#' + i);
  ALL[k + '#n'] = String(n);
  for (const key in W) ALL[key] = W[key];
}
