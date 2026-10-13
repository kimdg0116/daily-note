/**
 * 데일리 노트 동기화 서버 — 폰 앱과 맥(옵시디언 볼트)이 같은 데일리 노트를 쓰게 하는 우체통.
 * 맥 server.py 가 모든 데일리 노트를 올리고(mac), 폰은 받아 보고(get·docs) 고친 칸을 보낸다(edit).
 * 폰에서 고친 칸은 받은 편지함(ob)에 모였다가 맥이 가져가 볼트에 쓰고 받았다고 알린다(done).
 * 맥이 꺼져 있어도 폰 수정은 여기 남고, 폰에서 다시 열면 고친 대로 보인다.
 *
 * 저장: 노트 본문은 구글 시트 '데일리 노트 동기화 (앱 데이터)'의 notes 탭에 한 줄씩
 *       [날짜, rev, 내용 4칸 (gzip+base64, 칸마다 45000자, 앞에 ~)]. 노트가 몇 년 치 쌓여도 된다.
 *       작은 것(idx 날짜→[rev, 줄], meta, ob, 시트 id)은 Script Properties (gzip+base64, 8000자 조각).
 * 처음 한 번: 배포 주소(/exec)를 브라우저로 열어 권한을 허용하면 doGet 이 시트를 만든다.
 * 연결 코드는 Secret.js 의 CODE (git 제외, clasp 로만 올라감).
 *
 * 폰 → {code, op:'get', since}                → {rev, docs, dates?, mind?, wait:{날짜:칸 수}, macAt}   since 0 이면 최근 60일만
 * 폰 → {code, op:'docs', dates:[날짜…]}         → {docs}       예전 노트는 열 때 받아 간다
 * 폰 → {code, op:'edit', date, fm, sec, t}     → {rev}        fm/sec = {키: {v: 새 값, b: 폰이 본 값}}
 * 맥 → {code, op:'mac', put, keep, done, dates?, mind?} → {ob}   done = [[날짜, 'fm'|'sec', 키, t]]
 *
 * 반영: cd sync && ~/Desktop/app/dosimetrist-calendar-server/tools/node_modules/.bin/clasp push -f
 *       && …/clasp redeploy <배포 ID>   (배포 ID 는 server.py·index.html 의 SYNC_URL, URL 유지)
 */
const CH = 8000, CELL = 45000, COLS = 4, RECENT = 60;
let ALL, W, DEL, SH;                                         // 요청마다: 다 읽어 두고, 쓸 것·지울 것을 모아 한 번에

function doGet() {
  return ContentService.createTextOutput('데일리 노트 동기화 준비 완료 · 이 창은 닫아도 돼요 (시트 ' + setup_().slice(0, 6) + ')');
}

function setup_() {
  const p = PropertiesService.getScriptProperties(), all = p.getProperties();
  let id = all.sheet;
  if (!id) {
    const ss = SpreadsheetApp.create('데일리 노트 동기화 (앱 데이터)'), sh = ss.getSheets()[0].setName('notes');
    sh.getRange('A:B').setNumberFormat('@');                // 날짜가 날짜값으로 바뀌지 않게
    id = ss.getId();
    p.setProperty('sheet', id);
    Object.keys(all).filter(k => /^d:|^idx#/.test(k)).forEach(k => p.deleteProperty(k));   // 예전(속성에 노트 저장) 것 정리
  }
  return id;
}

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
    ALL = p.getProperties(); W = {}; DEL = []; SH = null;
    if (!ALL.sheet) return out_({ err: 'setup' });           // 아직 권한 허용(doGet) 전
    const r = OPS[q.op](q);
    if (Object.keys(W).length) p.setProperties(W);
    DEL.forEach(k => p.deleteProperty(k));
    return out_(r);
  } finally { lock.releaseLock(); }
}

const blank_ = d => ({ date: d, exists: false, fm: {}, sec: { tomorrow: '', today: '', journal: '' }, quote: { state: 'new' }, author: null });
const pending_ = o => Object.keys(o.fm || {}).length + Object.keys(o.sec || {}).length;
const ymd_ = t => Utilities.formatDate(new Date(t), 'Asia/Seoul', 'yyyy-MM-dd');

const OPS = {
  get(q) {
    const idx = getJ_('idx') || {}, meta = getJ_('meta') || {}, ob = getJ_('ob') || {}, since = +q.since || 0, wait = {};
    const lo = ymd_(Date.now() - RECENT * 864e5);
    const docs = readDocs_(Object.keys(idx).filter(d => since ? idx[d][0] > since : d >= lo), idx);
    for (const d in ob) wait[d] = pending_(ob[d]);
    const r = { rev: +ALL.rev || 0, docs, wait, macAt: meta.macAt || 0 };
    if ((meta.mrev || 0) > since) { r.dates = meta.dates || []; r.mind = meta.mind || []; }
    return r;
  },

  docs(q) {
    return { docs: readDocs_((q.dates || []).slice(0, 40), getJ_('idx') || {}) };
  },

  edit(q) {
    if (!/^\d{4}-\d{2}-\d{2}$/.test(q.date)) return { err: 'bad' };
    const ob = getJ_('ob') || {}, idx = getJ_('idx') || {}, o = ob[q.date] || (ob[q.date] = { fm: {}, sec: {} });
    const doc = readDocs_([q.date], idx)[q.date] || blank_(q.date), rev = (+ALL.rev || 0) + 1;
    for (const part of ['fm', 'sec']) for (const k in (q[part] || {})) {
      const e = q[part][k], prev = o[part][k];
      o[part][k] = { v: e.v, t: +q.t || Date.now(), b: prev ? prev.b : e.b };   // 폰이 본 값은 처음 고칠 때 것
      doc[part][k] = e.v;
    }
    writeDocs_({ [q.date]: doc }, idx, rev);
    setJ_('ob', ob); setJ_('idx', idx); W.rev = String(rev);
    return { rev };
  },

  mac(q) {
    const ob = getJ_('ob') || {}, idx = getJ_('idx') || {}, meta = getJ_('meta') || {}, rev = (+ALL.rev || 0) + 1, put = q.put || {};
    let touched = false;
    for (const [d, part, k, t] of q.done || []) {           // 맥이 볼트에 쓴 것 (그 사이 폰이 또 고쳤으면 남긴다)
      const e = ob[d] && ob[d][part] && ob[d][part][k];
      if (e && e.t === t) delete ob[d][part][k];
      if (ob[d] && !pending_(ob[d])) delete ob[d];
    }
    for (const d in put) {
      const o = ob[d];
      if (o) for (const part of ['fm', 'sec']) for (const k in o[part]) put[d][part][k] = o[part][k].v;   // 아직 볼트에 안 쓴 폰 수정은 위에 얹는다
    }
    if (q.keep) for (const d in idx) if (q.keep.indexOf(d) < 0 && !ob[d] && !(d in put)) put[d] = null;   // 맥에서 지운 노트
    if (Object.keys(put).length) { writeDocs_(put, idx, rev); touched = true; }
    if (q.dates) { meta.dates = q.dates; meta.mrev = rev; touched = true; }
    if (q.mind) { meta.mind = q.mind; meta.mrev = rev; touched = true; }
    meta.macAt = Date.now();
    setJ_('ob', ob); setJ_('idx', idx); setJ_('meta', meta);
    if (touched) W.rev = String(rev);
    return { ob };
  },
};

function out_(o) { return ContentService.createTextOutput(JSON.stringify(o)).setMimeType(ContentService.MimeType.JSON); }
const gz_ = v => Utilities.base64Encode(Utilities.gzip(Utilities.newBlob(JSON.stringify(v))).getBytes());
const ungz_ = s => JSON.parse(Utilities.ungzip(Utilities.newBlob(Utilities.base64Decode(s), 'application/x-gzip')).getDataAsString());

function sheet_() { return SH || (SH = SpreadsheetApp.openById(ALL.sheet).getSheetByName('notes')); }

function readDocs_(dates, idx) {                             // {날짜: 노트} — 시트에서 필요한 줄만
  const rows = dates.filter(d => idx[d]).map(d => idx[d][1]), out = {};
  if (!rows.length) return out;
  const lo = Math.min.apply(null, rows), hi = Math.max.apply(null, rows);
  const vals = sheet_().getRange(lo, 1, hi - lo + 1, 2 + COLS).getValues();
  for (const d of dates) {
    const r = idx[d] && vals[idx[d][1] - lo];
    if (r && String(r[0]) === d) out[d] = ungz_(r.slice(2).map(c => String(c).slice(1)).join(''));
  }
  return out;
}

function writeDocs_(docs, idx, rev) {                        // 노트 = 시트 한 줄, null 이면 지운다 (줄은 비워 둔다)
  const sh = sheet_(), adds = [];
  for (const d in docs) {
    if (docs[d] == null) {
      if (idx[d]) { sh.getRange(idx[d][1], 1, 1, 2 + COLS).clearContent(); delete idx[d]; }
      continue;
    }
    const s = gz_(docs[d]), row = [d, String(rev)];
    for (let i = 0; i < COLS; i++) row.push(i * CELL < s.length ? '~' + s.slice(i * CELL, (i + 1) * CELL) : '');
    if (s.length > COLS * CELL) throw new Error('노트가 너무 길어요: ' + d);
    if (idx[d]) { sh.getRange(idx[d][1], 1, 1, row.length).setValues([row]); idx[d][0] = rev; }
    else adds.push(row);
  }
  if (adds.length) {
    const start = sh.getLastRow() + 1;
    sh.getRange(start, 1, adds.length, 2 + COLS).setValues(adds);
    adds.forEach((row, i) => { idx[row[0]] = [rev, start + i]; });
  }
}

function getJ_(k) {
  const n = +ALL[k + '#n'] || 0;
  if (!n) return null;
  let s = '';
  for (let i = 0; i < n; i++) s += ALL[k + '#' + i];
  return ungz_(s);
}

function setJ_(k, v) {                                       // v 가 null 이면 지운다
  const old = +ALL[k + '#n'] || 0;
  let n = 0;
  if (v != null) {
    const s = gz_(v);
    n = Math.ceil(s.length / CH);
    for (let i = 0; i < n; i++) W[k + '#' + i] = s.slice(i * CH, (i + 1) * CH);
    W[k + '#n'] = String(n);
  } else if (old) DEL.push(k + '#n');
  for (let i = n; i < old; i++) DEL.push(k + '#' + i);
  ALL[k + '#n'] = String(n);
  for (const key in W) ALL[key] = W[key];
}
