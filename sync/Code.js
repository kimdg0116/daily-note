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
 * 폰 → {code, op:'get', since, meta?}              → {rev, docs:{날짜:노트}, stale?, want?, dates?, mind?, quotes?, plans?, wait:{날짜:칸 수}, pwait:[id], macAt}
 * 폰 → {code, op:'want'}                    → {ok}       모든 노트 다시 받기 (처음 연결할 때)
 * 위젯 → {code, op:'widget', today, yday}   → {today:{today?, tomorrow?}|null, yday:…}   할 일 칸만, 읽기만
 * 폰 → {code, op:'edit', date, fm, sec, t}  → {ok}       fm/sec = {키: {v: 새 값, b: 폰이 본 값}}
 * 폰 → {code, op:'plan', ops}             → {ok}       일정 바꾸기 [{id, act:'add'|'toggle', d, n, on?}] (맥이 일정 노트에 쓴다)
 * 폰 → {code, op:'rwant', rels}            → {ok}       읽을 글 본문을 달라고 (맥이 다음에 들를 때 캐시에 넣는다)
 * 폰 → {code, op:'rget', rels}             → {docs:{rel: 본문}}   캐시에 들어온 본문만 (없으면 빠진다 → 폰이 다시 달라고 한다)
 * 폰 → {code, op:'rmark', marks}           → {ok}       읽음·메모·되돌리기 [{rel, on, memo, day, t}] (같은 글은 나중 것만, 맥이 노트에 쓴다)
 * 폰 → {code, op:'iwant', names}           → {ok}       본문 속 볼트 그림을 달라고 (맥이 줄여서 캐시에 넣는다)
 * 폰 → {code, op:'img', names}             → {imgs:{이름: data URL}}   캐시에 들어온 그림만 (없으면 빠진다 → 폰이 다시 달라고 한다)
 * 맥 → {code, op:'mac', put, keep?, done, pdone?, resync?, dates?, mind?, quotes?, plans?, reads?, theme?, rput?, rqdone?, rdone?, iput?, iqdone?} → {ob, want, po, rq, rob, iq}
 *        quotes = 명언 모음 {list, favs}, plans = 일정 [{d, n, x}], po = 아직 맥이 안 쓴 일정 바꾸기, pdone = 맥이 쓴 것의 id
 *        resync = {to: 이번 묶음 마지막 날짜, done: 끝인지}, done = [[날짜, 'fm'|'sec', 키, t]]
 *        reads = 읽을 글 목록, theme = 옵시디언 테마 CSS, rput = {id: 본문}, rqdone = 넣은(또는 없는) 글, rdone = [[rel, t]] 맥이 노트에 쓴 읽음
 * 읽을 글 본문(rput)과 그림(iput)은 Script Properties(500KB)에 안 넣고 Script Cache 에 6시간만 둔다 (값 하나 100KB 까지라 90000자씩 나눈다).
 * 폰이 목록의 본문을 전부(압축 1~2MB) 받아 둘 수 있게. 권한이 더 필요 없다
 *
 * 반영: cd sync && ~/Code/apps/dosimetrist-calendar-server/tools/node_modules/.bin/clasp push -f
 *       && …/clasp redeploy <배포 ID>   (배포 ID 는 server.py·index.html 의 SYNC_URL, URL 유지)
 */
const IMG_TTL = 21600, ICH = 90000;                           // 그림·본문: 캐시에 6시간, 90000자 조각
const CH = 8000, BOX = 280000;                               // 노트 상자 한도 (전체 저장 한도 500KB 안에 목록·테마까지)
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
    ALL = p.getProperties(); W = {}; DEL = Object.keys(ALL).filter(k => /^(d:|idx#|sheet$|ri#|rb:)/.test(k));   // 예전 방식(노트 보관, 본문 상자)의 흔적은 지운다
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
    if ((meta.mrev || 0) > since || q.meta) { r.dates = meta.dates || []; r.mind = meta.mind || []; r.quotes = meta.quotes || null; r.plans = meta.plans || null; r.reads = meta.reads || null; r.theme = meta.theme || null; }   // meta = 놓친 폰이 다시 달라고
    r.rwait = Object.keys(getJ_('rob') || {});              // 아직 맥이 노트에 안 쓴 읽음
    r.pwait = (getJ_('po') || []).map(o => o.id);
    const want = getJ_('want');
    if (want) {
      want.seen = rev;                                        // 폰이 지금까지 넣은 걸 다 받았다
      if (want.done && want.seen >= want.sent) setJ_('want', null);
      else { setJ_('want', want); r.want = true; }
    }
    return r;
  },

  // 아이폰 위젯: 오늘·어제 노트의 할 일 칸만. 읽기만 한다 (get 은 want.seen 을 바꾸므로 위젯이 쓰면 안 된다)
  // 아직 맥이 볼트에 안 쓴 폰 수정(ob)을 얹어서 → 폰 앱에서 체크하면 맥이 꺼져 있어도 위젯에 보인다. 노트도 수정도 없으면 null
  widget(q) {
    const ob = getJ_('ob') || {}, bi = getJ_('bi') || {};
    const tasks = d => {
      if (!/^\d{4}-\d{2}-\d{2}$/.test(d || '')) return null;
      const s = bi[d] && (getJ_('b:' + d) || {}).sec, o = (ob[d] && ob[d].sec) || {}, r = {};
      for (const k of ['today', 'tomorrow']) if (k in o) r[k] = o[k].v; else if (s && k in s) r[k] = s[k];
      return Object.keys(r).length ? r : null;
    };
    return { today: tasks(q.today), yday: tasks(q.yday) };
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

  rwant(q) {                                                 // 폰이 달라는 읽을 글 본문 (맥이 넣으면 rqdone 으로 지운다)
    const rq = getJ_('rq') || [];
    for (const rel of q.rels || []) if (typeof rel === 'string' && rel && !rq.includes(rel)) rq.push(rel);
    setJ_('rq', rq.slice(-400));
    return { ok: true };
  },

  rmark(q) {                                                 // 폰에서 누른 읽음·메모·되돌리기. 같은 글은 나중 것만
    const rob = getJ_('rob') || {};
    for (const m of q.marks || []) if (m && typeof m.rel === 'string' && m.rel)
      rob[m.rel] = { on: !!m.on, memo: String(m.memo || '').slice(0, 3000), day: String(m.day || ''), t: +m.t || Date.now() };
    setJ_('rob', rob);
    return { ok: true };
  },

  iwant(q) {                                                 // 폰이 달라는 볼트 그림 이름 (맥이 넣으면 iqdone 으로 지운다)
    const iq = getJ_('iq') || [];
    for (const n of q.names || []) if (typeof n === 'string' && n && n.length < 200 && !iq.includes(n)) iq.push(n);
    setJ_('iq', iq.slice(-200));
    return { ok: true };
  },

  img(q) {                                                   // 캐시에 있는 그림
    const names = (q.names || []).filter(n => typeof n === 'string').slice(0, 12);
    const got = cget_(names.map(n => 'i:' + n)), out = {};
    names.forEach(n => { if (got['i:' + n] != null) out[n] = got['i:' + n]; });
    return { imgs: out };
  },

  rget(q) {                                                  // 캐시에 있는 읽을 글 본문
    const rels = (q.rels || []).filter(n => typeof n === 'string').slice(0, 40);
    const got = cget_(rels.map(rkey_)), out = {};
    rels.forEach(n => { const s = got[rkey_(n)]; if (s != null) out[n] = JSON.parse(ungz_(s)); });
    return { docs: out };
  },

  plan(q) {                                                  // 폰에서 바꾼 일정. 같은 id 는 한 번만
    const po = getJ_('po') || [];
    for (const o of q.ops || []) if (o && o.id && !po.some(x => x.id === o.id)) po.push(o);
    setJ_('po', po.slice(-200));
    return { ok: true };
  },

  mac(q) {
    const ob = getJ_('ob') || {}, bi = getJ_('bi') || {}, meta = getJ_('meta') || {}, put = q.put || {};
    let rev = +ALL.rev || 0, want = getJ_('want'), po = getJ_('po') || [], rq = getJ_('rq') || [], rob = getJ_('rob') || {};
    const rput = q.rput || {};
    let iq = getJ_('iq') || [];
    if ((q.iqdone || []).length) { iq = iq.filter(x => !q.iqdone.includes(x)); setJ_('iq', iq.length ? iq : null); }
    const cput = {};                                          // 맥이 줄여 보낸 그림(폰이 img 로) · 폰이 달란 본문(rget 으로) → 캐시에
    for (const n in q.iput || {}) cput['i:' + n] = String(q.iput[n]);
    for (const id in rput) if (rput[id] && typeof rput[id].rel === 'string') cput[rkey_(rput[id].rel)] = gz_(rput[id]);
    cputAll_(cput);
    if ((q.rqdone || []).length) { rq = rq.filter(x => !q.rqdone.includes(x)); setJ_('rq', rq.length ? rq : null); }
    if ((q.rdone || []).length) {                            // 맥이 노트에 쓴 읽음 (그 사이 폰이 또 눌렀으면 남긴다)
      for (const [rel, t] of q.rdone) if (rob[rel] && rob[rel].t === t) delete rob[rel];
      setJ_('rob', Object.keys(rob).length ? rob : null);
    }
    if ((q.pdone || []).length) { po = po.filter(o => !q.pdone.includes(o.id)); setJ_('po', po.length ? po : null); }   // 맥이 일정 노트에 쓴 것
    for (const [d, part, k, t] of q.done || []) {           // 맥이 볼트에 쓴 것 (그 사이 폰이 또 고쳤으면 남긴다)
      const e = ob[d] && ob[d][part] && ob[d][part][k];
      if (e && e.t === t) delete ob[d][part][k];
      if (ob[d] && !pending_(ob[d])) delete ob[d];
    }
    if (Object.keys(put).length || q.dates || q.mind || q.quotes || q.plans || q.reads || q.theme != null) rev++;
    for (const d in put) {
      const o = ob[d];
      if (o) for (const part of ['fm', 'sec']) for (const k in o[part]) put[d][part][k] = o[part][k].v;   // 아직 볼트에 안 쓴 폰 수정은 위에 얹는다
      bi[d] = [rev, setJ_('b:' + d, put[d])];
    }
    if (q.resync && want) { want.from = q.resync.to; want.sent = rev; want.done = !!q.resync.done; setJ_('want', want); }
    if (q.dates) { meta.dates = q.dates; meta.mrev = rev; }
    if (q.mind) { meta.mind = q.mind; meta.mrev = rev; }
    if (q.quotes) { meta.quotes = q.quotes; meta.mrev = rev; }
    if (q.plans) { meta.plans = q.plans; meta.mrev = rev; }
    if (q.reads) { meta.reads = q.reads; meta.mrev = rev; }
    if (q.theme != null) { meta.theme = q.theme; meta.mrev = rev; }
    meta.macAt = Date.now();
    setJ_('ob', ob);
    if (Object.keys(put).length) { fit_(bi, meta); setJ_('bi', bi); }
    setJ_('meta', meta);
    W.rev = String(rev);
    return { ob, want, po, rq, rob, iq };
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

// 캐시 키는 250자까지라 본문은 경로의 MD5 로
const rkey_ = rel => 'r:' + Utilities.base64Encode(Utilities.computeDigest(Utilities.DigestAlgorithm.MD5, rel, Utilities.Charset.UTF_8));

function cputAll_(vals) {                                     // 캐시에 6시간 (값 하나 100KB 까지라 ICH 자씩 나눈다)
  const all = {};
  for (const k in vals) {
    const s = vals[k], n = Math.ceil(s.length / ICH);
    for (let i = 0; i < n; i++) all[k + '#' + i] = s.slice(i * ICH, (i + 1) * ICH);
    all[k + '#n'] = String(n);
  }
  const ks = Object.keys(all);
  for (let i = 0; i < ks.length; i += 100) CacheService.getScriptCache().putAll(Object.fromEntries(ks.slice(i, i + 100).map(k => [k, all[k]])), IMG_TTL);   // 한 번에 100개씩
}

function cget_(keys) {                                        // 캐시에서 조각을 이어 붙여서 (조각이 하나라도 없으면 빼고)
  const cache = CacheService.getScriptCache(), heads = cache.getAll(keys.map(k => k + '#n')), out = {};
  for (const k of keys) {
    const n = +heads[k + '#n'] || 0, ks = [];
    for (let i = 0; i < n; i++) ks.push(k + '#' + i);
    const parts = n ? cache.getAll(ks) : {};
    if (n && ks.every(x => parts[x] != null)) out[k] = ks.map(x => parts[x]).join('');
  }
  return out;
}

function out_(o) { return ContentService.createTextOutput(JSON.stringify(o)).setMimeType(ContentService.MimeType.JSON); }
const gz_ = v => Utilities.base64Encode(Utilities.gzip(Utilities.newBlob(JSON.stringify(v))).getBytes());
const ungz_ = s => Utilities.ungzip(Utilities.newBlob(Utilities.base64Decode(s), 'application/x-gzip')).getDataAsString();

function getJ_(k) {
  const n = +ALL[k + '#n'] || 0;
  if (!n) return null;
  let s = '';
  for (let i = 0; i < n; i++) s += ALL[k + '#' + i];
  return JSON.parse(ungz_(s));
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
