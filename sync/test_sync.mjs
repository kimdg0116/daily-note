// node sync/test_sync.mjs - 동기화 서버(Code.js)를 가짜 구글 서비스 위에서 돌려 본다 (실제 서버는 건드리지 않는다)
// node sync/test_sync.mjs --serve - 같은 가짜를 http://127.0.0.1:8751 로 띄운다 (폰 화면·맥 서버를 붙여 시험할 때. 코드는 Secret.js)
import { readFileSync } from 'node:fs';
import { randomBytes } from 'node:crypto';
import { gzipSync, gunzipSync } from 'node:zlib';
import assert from 'node:assert/strict';
import { createServer } from 'node:http';
const store = {}, cache = {};
const blob = b => ({ b: Buffer.from(b), getBytes() { return this.b; }, getDataAsString() { return this.b.toString(); } });
const g = {
  PropertiesService: { getScriptProperties: () => ({ getProperties: () => ({ ...store }), setProperties: o => Object.assign(store, o), deleteProperty: k => delete store[k] }) },
  CacheService: { getScriptCache: () => ({ get: k => cache[k] ?? null, put: (k, v) => { cache[k] = v; } }) },
  LockService: { getScriptLock: () => ({ waitLock() {}, releaseLock() {} }) },
  ContentService: { MimeType: { JSON: 'json' }, createTextOutput: s => ({ setMimeType: () => s }) },
  Utilities: { newBlob: s => blob(s), gzip: b => blob(gzipSync(b.b)), ungzip: b => blob(gunzipSync(b.b)), base64Encode: b => Buffer.from(b).toString('base64'), base64Decode: s => Buffer.from(s, 'base64') },
};
const SERVE = process.argv.includes('--serve');
const code = SERVE ? readFileSync(new URL('./Secret.js', import.meta.url), 'utf8').match(/CODE = '(\w+)'/)[1] : 'ABC';
const src = readFileSync(new URL('./Code.js', import.meta.url), 'utf8') + `\nconst CODE = '${code}';\nreturn doPost;`;
const doPost = new Function(...Object.keys(g), src)(...Object.values(g));
if (SERVE) {
  createServer((req, res) => {
    let b = '';
    req.on('data', c => b += c).on('end', () => {
      res.writeHead(200, { 'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*' });
      res.end(req.method === 'POST' ? doPost({ postData: { contents: b } }) : '{}');
    });
  }).listen(8751, '127.0.0.1', () => console.log('가짜 연동 서버 http://127.0.0.1:8751'));
} else {
const call = q => JSON.parse(doPost({ postData: { contents: JSON.stringify({ code: 'ABC', ...q }) } }));
const doc = (d, mood, j = '') => ({ date: d, exists: true, fm: { mood }, sec: { tomorrow: '', today: '', journal: j }, quote: { state: 'done' } });
const [A, B, C] = ['2025-01-01', '2026-10-12', '2026-10-13'];
store['d:old#n'] = '1'; store['idx#n'] = '1'; store.sheet = 'x';
assert.equal(call({ code: 'nope', op: 'get' }).err, 'code');
// 맥 첫 연결: 노트는 안 보내고 목록·양식만
assert.equal(call({ op: 'mac', put: {}, dates: [A, B, C], mind: [{ name: '회고' }] }).want, null);
assert.ok(!Object.keys(store).some(k => /^(d:|idx#|sheet$)/.test(k)));               // 예전 방식 흔적 정리
// 새 폰: 목록 받고, 모든 노트 다시 받기를 건다
let r = call({ op: 'get', since: 0 });
assert.deepEqual(r.dates, [A, B, C]); assert.deepEqual(r.docs, {}); assert.equal(r.want, undefined);
call({ op: 'want' });
// 맥이 묶음을 나눠 보내고, 폰이 받은 걸 확인한 뒤에 다음 묶음
let w = call({ op: 'mac' }).want;
assert.deepEqual(w, { from: '', sent: 0, seen: 0, done: false });
w = call({ op: 'mac', put: { [A]: doc(A, 1), [B]: doc(B, 2) }, resync: { to: B, done: false } }).want;
assert.ok(w.sent > w.seen);                                                              // 폰이 아직 안 받음 → 맥은 기다린다
r = call({ op: 'get', since: 0 });
assert.deepEqual(Object.keys(r.docs).sort(), [A, B]); assert.equal(r.want, true);
w = call({ op: 'mac' }).want; assert.ok(w.seen >= w.sent && w.from === B);
call({ op: 'mac', put: { [C]: doc(C, 3) }, resync: { to: C, done: true } });
const rev1 = r.rev;
r = call({ op: 'get', since: rev1 });
assert.deepEqual(Object.keys(r.docs), [C]); assert.equal(r.want, undefined);              // 다 받음
assert.equal(call({ op: 'mac' }).want, null);
// 명언 모음은 바뀔 때만 오고, 폰이 받아 간 뒤로는 안 온다
const Q = { list: [{ date: B, text: 'Be kind.', toggle: true, on: true }], favs: [B] };
call({ op: 'mac', quotes: Q });
r = call({ op: 'get', since: rev1 });
assert.deepEqual(r.quotes, Q); assert.equal(call({ op: 'get', since: r.rev }).quotes, undefined);
// 폰 수정 → 받은 편지함 → 맥이 옛 노트를 올려도 폰 수정을 얹어서 보낸다
const rev2 = r.rev;
call({ op: 'edit', date: C, fm: { mood: { v: 4, b: 3 } }, t: 1000 });
assert.deepEqual(call({ op: 'get', since: rev2 }).wait, { [C]: 1 });
let ob = call({ op: 'mac', put: { [C]: doc(C, 3) } }).ob;
assert.deepEqual(ob[C].fm.mood, { v: 4, t: 1000, b: 3 });
assert.equal(call({ op: 'get', since: rev2 }).docs[C].fm.mood, 4);
// 맥이 가져간 뒤 폰이 또 고치면, 맥의 확인(t=1000)으로는 지워지지 않는다
call({ op: 'edit', date: C, fm: { mood: { v: 5, b: 4 } }, t: 2000 });
assert.deepEqual(call({ op: 'mac', done: [[C, 'fm', 'mood', 1000]] }).ob[C].fm.mood, { v: 5, t: 2000, b: 3 });
assert.deepEqual(call({ op: 'mac', done: [[C, 'fm', 'mood', 2000]], put: { [C]: doc(C, 5) } }).ob, {});
// 상자가 넘치면 오래된 것부터 버리고, 그보다 오래 안 들른 폰은 처음부터 다시 받는다
const stale = call({ op: 'get', since: 0 }).rev;
for (let i = 0; i < 6; i++) call({ op: 'mac', put: { [`2026-09-0${i + 1}`]: doc(`2026-09-0${i + 1}`, 1, randomBytes(60000).toString('base64')) } });
assert.ok(Object.keys(store).filter(k => k.startsWith('b:') && !k.endsWith('#n')).reduce((n, k) => n + store[k].length, 0) <= 300000);
assert.equal(call({ op: 'get', since: stale }).stale, true);
const fresh = call({ op: 'get', since: 0 }).rev;
call({ op: 'mac', put: { [C]: doc(C, 1) } });
assert.equal(call({ op: 'get', since: fresh }).stale, undefined);                         // 자주 들르면 괜찮다
console.log('ok');
}
