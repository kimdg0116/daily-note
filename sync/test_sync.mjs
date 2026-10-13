// node sync/test_sync.mjs - 동기화 서버(Code.js)를 가짜 구글 서비스 위에서 돌려 본다 (실제 서버는 건드리지 않는다)
// node sync/test_sync.mjs --serve - 같은 가짜를 http://127.0.0.1:8751 로 띄운다 (폰 화면·맥 서버를 붙여 시험할 때. 코드는 Secret.js)
import { readFileSync } from 'node:fs';
import assert from 'node:assert/strict';
import { createServer } from 'node:http';
const store = {}, cache = {};
const blob = s => ({ s, getBytes: () => s, getDataAsString: () => s });
const g = {
  PropertiesService: { getScriptProperties: () => ({ getProperties: () => ({ ...store }), setProperties: o => Object.assign(store, o), deleteProperty: k => delete store[k] }) },
  CacheService: { getScriptCache: () => ({ get: k => cache[k] ?? null, put: (k, v) => { cache[k] = v; } }) },
  LockService: { getScriptLock: () => ({ waitLock() {}, releaseLock() {} }) },
  ContentService: { MimeType: { JSON: 'json' }, createTextOutput: s => ({ setMimeType: () => s }) },
  Utilities: { newBlob: s => blob(s), gzip: b => b, ungzip: b => b, base64Encode: s => Buffer.from(s).toString('base64'), base64Decode: s => Buffer.from(s, 'base64').toString() },
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

assert.equal(call({ code: 'nope', op: 'get' }).err, 'code');
const doc = (mood, j = '') => ({ date: '2026-10-13', exists: true, fm: { mood }, sec: { tomorrow: '', today: '', journal: j }, quote: { state: 'done' } });
assert.deepEqual(call({ op: 'mac', put: { '2026-10-13': doc(3) }, keep: ['2026-10-13'], dates: ['2026-10-13'], mind: [{ name: '회고' }] }).ob, {});
let r = call({ op: 'get', since: 0 });
assert.equal(r.docs['2026-10-13'].fm.mood, 3); assert.deepEqual(r.dates, ['2026-10-13']); assert.equal(r.mind[0].name, '회고');
const rev0 = r.rev;
call({ op: 'edit', date: '2026-10-13', fm: { mood: { v: 4, b: 3 } }, t: 1000 });
r = call({ op: 'get', since: rev0 });
assert.equal(r.docs['2026-10-13'].fm.mood, 4); assert.deepEqual(r.wait, { '2026-10-13': 1 }); assert.equal(r.dates, undefined);
// 맥이 아직 옛 노트를 올려도 폰 수정은 위에 남는다
let ob = call({ op: 'mac', put: { '2026-10-13': doc(3) }, keep: ['2026-10-13'] }).ob;
assert.deepEqual(ob['2026-10-13'].fm.mood, { v: 4, t: 1000, b: 3 });
assert.equal(call({ op: 'get', since: 0 }).docs['2026-10-13'].fm.mood, 4);
// 맥이 가져간 뒤 폰이 또 고치면, 맥의 확인(t=1000)으로는 지워지지 않는다
call({ op: 'edit', date: '2026-10-13', fm: { mood: { v: 5, b: 4 } }, t: 2000 });
ob = call({ op: 'mac', done: [['2026-10-13', 'fm', 'mood', 1000]] }).ob;
assert.deepEqual(ob['2026-10-13'].fm.mood, { v: 5, t: 2000, b: 3 });
ob = call({ op: 'mac', done: [['2026-10-13', 'fm', 'mood', 2000]], put: { '2026-10-13': doc(5) } }).ob;
assert.deepEqual(ob, {}); assert.deepEqual(call({ op: 'get', since: 0 }).wait, {});
// 새 날(맥에 노트 없음)도 폰에서 쓸 수 있고, 맥이 볼트에 쓰기 전까지 지워지지 않는다
call({ op: 'edit', date: '2026-10-15', sec: { journal: { v: '폰에서 씀', b: '' } }, t: 3000 });
call({ op: 'mac', keep: ['2026-10-13'] });
assert.equal(call({ op: 'get', since: 0 }).docs['2026-10-15'].sec.journal, '폰에서 씀');
// 긴 글은 조각으로 나눠 저장
const long = '가'.repeat(30000);
call({ op: 'mac', put: { '2026-10-13': doc(5, long) }, keep: ['2026-10-13', '2026-10-15'] });
assert.ok(+store['d:2026-10-13#n'] > 1); assert.equal(call({ op: 'get', since: 0 }).docs['2026-10-13'].sec.journal, long);
call({ op: 'mac', put: { '2026-10-13': doc(5) }, keep: ['2026-10-13', '2026-10-15'] });
assert.equal(store['d:2026-10-13#1'], undefined);                          // 짧아지면 남은 조각을 지운다
// 창 밖으로 나간 날은 지운다
call({ op: 'mac', done: [['2026-10-15', 'sec', 'journal', 3000]], keep: ['2026-10-15'] });
assert.deepEqual(Object.keys(call({ op: 'get', since: 0 }).docs), ['2026-10-15']);
console.log('ok');
}
