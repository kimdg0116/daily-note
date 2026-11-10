// node sync/test_sync.mjs - 동기화 서버(Code.js)를 가짜 구글 서비스 위에서 돌려 본다 (실제 서버는 건드리지 않는다)
// node sync/test_sync.mjs --serve - 같은 가짜를 http://127.0.0.1:8751 로 띄운다 (폰 화면·맥 서버를 붙여 시험할 때. 코드는 Secret.js)
import { readFileSync } from 'node:fs';
import { randomBytes, createHash } from 'node:crypto';
import { gzipSync, gunzipSync } from 'node:zlib';
import assert from 'node:assert/strict';
import { createServer } from 'node:http';
const store = {}, cache = {};
const blob = b => ({ b: Buffer.from(b), getBytes() { return this.b; }, getDataAsString() { return this.b.toString(); } });
const g = {
  PropertiesService: { getScriptProperties: () => ({ getProperties: () => ({ ...store }), setProperties: o => Object.assign(store, o), deleteProperty: k => delete store[k] }) },
  CacheService: { getScriptCache: () => ({ get: k => cache[k] ?? null, put: (k, v) => { cache[k] = v; }, putAll: o => Object.assign(cache, o),
    getAll: ks => Object.fromEntries(ks.filter(k => k in cache).map(k => [k, cache[k]])) }) },
  LockService: { getScriptLock: () => ({ waitLock() {}, releaseLock() {} }) },
  ContentService: { MimeType: { JSON: 'json' }, createTextOutput: s => ({ setMimeType: () => s }) },
  Utilities: { newBlob: s => blob(s), gzip: b => blob(gzipSync(b.b)), ungzip: b => blob(gunzipSync(b.b)), base64Encode: b => Buffer.from(b).toString('base64'), base64Decode: s => Buffer.from(s, 'base64'),
    computeDigest: (a, s) => [...createHash('md5').update(s, 'utf8').digest()], DigestAlgorithm: { MD5: 'md5' }, Charset: { UTF_8: 'utf8' } },
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
assert.deepEqual(call({ op: 'get', since: r.rev, meta: true }).quotes, Q);              // 놓친 폰은 다시 받는다
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
// 위젯: 할 일 칸만, 폰 수정을 얹고, 아무것도 안 바꾼다
const tdoc = (d, today, tomorrow) => ({ ...doc(d, 1), sec: { today, tomorrow, journal: 'x' } });
call({ op: 'mac', put: { [B]: tdoc(B, '- [ ] a', '- [ ] b') } });
call({ op: 'edit', date: C, sec: { tomorrow: { v: '- [ ] c', b: '' } }, t: 3000 });
const before = JSON.stringify(store);
assert.deepEqual(call({ op: 'widget', today: C, yday: B }), { today: { today: '', tomorrow: '- [ ] c' }, yday: { today: '- [ ] a', tomorrow: '- [ ] b' } });
assert.deepEqual(call({ op: 'widget', today: '2030-01-01', yday: 'bad' }), { today: null, yday: null });
assert.equal(JSON.stringify(store), before);
call({ op: 'mac', done: [[C, 'sec', 'tomorrow', 3000]] });
// 일정: 폰이 바꾼 것은 맥이 가져가 노트에 쓰고 pdone 으로 알리면 지워진다 (같은 id 는 한 번만). 일정 목록은 바뀔 때만 폰에
const rev3 = call({ op: 'get', since: 0 }).rev, op1 = { id: 'a1', act: 'add', d: C, n: '시험' };
call({ op: 'plan', ops: [op1] }); call({ op: 'plan', ops: [op1, { act: 'add', d: C, n: 'id 없음' }] });
assert.deepEqual(call({ op: 'get', since: rev3 }).pwait, ['a1']);
assert.deepEqual(call({ op: 'mac' }).po, [op1]);
const PL = [{ d: C, n: '시험', x: false }];
assert.deepEqual(call({ op: 'mac', pdone: ['a1'], plans: PL }).po, []);
r = call({ op: 'get', since: rev3 });
assert.deepEqual(r.plans, PL); assert.deepEqual(r.pwait, []); assert.equal(call({ op: 'get', since: r.rev }).plans, undefined);
// 상자가 넘치면 오래된 것부터 버리고, 그보다 오래 안 들른 폰은 처음부터 다시 받는다
const stale = call({ op: 'get', since: 0 }).rev;
for (let i = 0; i < 6; i++) call({ op: 'mac', put: { [`2026-09-0${i + 1}`]: doc(`2026-09-0${i + 1}`, 1, randomBytes(60000).toString('base64')) } });
assert.ok(Object.keys(store).filter(k => k.startsWith('b:') && !k.endsWith('#n')).reduce((n, k) => n + store[k].length, 0) <= 300000);
assert.equal(call({ op: 'get', since: stale }).stale, true);
const fresh = call({ op: 'get', since: 0 }).rev;
call({ op: 'mac', put: { [C]: doc(C, 1) } });
assert.equal(call({ op: 'get', since: fresh }).stale, undefined);                         // 자주 들르면 괜찮다
// 읽을 글: 목록·테마는 meta 로, 본문은 폰이 달라는 것만 캐시에 (rget 으로 가져간다). 맥이 넣으면 요청에서 빠진다
const R1 = '03 Economy/개념/듀레이션.md', R2 = '04 Life/읽을거리/깊게 읽기.md', LIST = [{ rel: R1, title: '듀레이션', read_on: '', v: 1 }];
const rr = call({ op: 'get', since: 0 }).rev;
call({ op: 'mac', reads: LIST, theme: '.ink { --x: 1 }' });
r = call({ op: 'get', since: rr });
assert.deepEqual(r.reads, LIST); assert.equal(r.theme, '.ink { --x: 1 }');
call({ op: 'rwant', rels: [R1, R2, R1, 5] });
assert.deepEqual(call({ op: 'mac' }).rq, [R1, R2]);
assert.deepEqual(call({ op: 'rget', rels: [R1] }).docs, {});                                  // 아직 안 넣었다
const propsR = JSON.stringify(Object.keys(store).filter(k => !k.startsWith('rq')).sort());
assert.deepEqual(call({ op: 'mac', rput: { a1b2: { rel: R1, html: '<p>본문</p>', v: 1 } }, rqdone: [R1] }).rq, [R2]);
assert.deepEqual(call({ op: 'rget', rels: [R1, R2] }).docs, { [R1]: { rel: R1, html: '<p>본문</p>', v: 1 } });
assert.equal(JSON.stringify(Object.keys(store).filter(k => !k.startsWith('rq')).sort()), propsR);   // Script Properties 에는 안 남는다
const LONG = '04 Life/읽을거리/' + '아주 긴 제목'.repeat(40) + '.md', BODY = randomBytes(200000).toString('base64');   // 캐시 키 한도(250자)를 넘는 경로 · 여러 조각
call({ op: 'mac', rput: { l1: { rel: LONG, html: BODY } } });
assert.equal(call({ op: 'rget', rels: [LONG] }).docs[LONG].html, BODY);
assert.ok(Object.keys(cache).every(k => k.length < 250));
const many = Array.from({ length: 300 }, (_, i) => 'n' + i + '.md');                           // 목록 전부를 한 번에 달라고 해도 큐에 다 남는다
call({ op: 'rwant', rels: many });
assert.equal(call({ op: 'mac' }).rq.length, 301);
call({ op: 'mac', rqdone: many });
// 읽음: 같은 글은 나중 것만. 맥이 쓰고 rdone 으로 알리면 빠진다 (그 사이 또 눌렀으면 남긴다)
call({ op: 'rmark', marks: [{ rel: R1, on: true, memo: '한 줄', day: '2026-11-09', t: 10 }, { rel: 7 }] });
assert.deepEqual(call({ op: 'get', since: 0 }).rwait, [R1]);
assert.deepEqual(call({ op: 'mac' }).rob, { [R1]: { on: true, memo: '한 줄', day: '2026-11-09', t: 10 } });
call({ op: 'rmark', marks: [{ rel: R1, on: false, day: '2026-11-09', t: 20 }] });
assert.deepEqual(Object.keys(call({ op: 'mac', rdone: [[R1, 10]] }).rob), [R1]);
assert.deepEqual(call({ op: 'mac', rdone: [[R1, 20]] }).rob, {});
assert.deepEqual(call({ op: 'get', since: 0 }).rwait, []);
// 예전 본문 상자(ri, rb:) 흔적은 지운다
store['ri#n'] = '1'; store['ri#0'] = 'x'; store['rb:abc#n'] = '1'; store['rb:abc#0'] = 'x';
call({ op: 'get', since: 0 });
assert.ok(!Object.keys(store).some(k => /^(ri#|rb:)/.test(k)));
// 그림: 폰이 이름으로 달라고 → 맥이 iq 로 받아 캐시에 넣고 iqdone → 폰이 img 로 가져간다 (Script Properties 에는 안 남는다)
const G = '메르 그림 01.png', BIG = 'data:image/jpeg;base64,' + randomBytes(150000).toString('base64');
call({ op: 'iwant', names: [G, G, 3, 'x'.repeat(300)] });
assert.deepEqual(call({ op: 'mac' }).iq, [G]);
assert.deepEqual(call({ op: 'img', names: [G] }).imgs, {});                                   // 아직 안 넣었다
const propsBefore = JSON.stringify(Object.keys(store).filter(k => !k.startsWith('iq')).sort());
assert.deepEqual(call({ op: 'mac', iput: { [G]: BIG }, iqdone: [G] }).iq, []);
assert.equal(call({ op: 'img', names: [G, '없는 그림'] }).imgs[G], BIG);                       // 여러 조각을 이어 붙인다
assert.ok(!Object.keys(store).some(k => k.startsWith('i:')));
assert.equal(JSON.stringify(Object.keys(store).filter(k => !k.startsWith('iq')).sort()), propsBefore);
console.log('ok');
}
