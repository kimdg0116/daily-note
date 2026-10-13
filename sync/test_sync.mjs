// node sync/test_sync.mjs - 동기화 서버(Code.js)를 가짜 구글 서비스 위에서 돌려 본다 (실제 서버는 건드리지 않는다)
// node sync/test_sync.mjs --serve - 같은 가짜를 http://127.0.0.1:8751 로 띄운다 (폰 화면·맥 서버를 붙여 시험할 때. 코드는 Secret.js)
import { readFileSync } from 'node:fs';
import { randomBytes } from 'node:crypto';
import { gzipSync, gunzipSync } from 'node:zlib';
import assert from 'node:assert/strict';
import { createServer } from 'node:http';
const store = {}, cache = {}, cells = [];                         // cells[줄][칸] (1부터)
const range = (r, c, nr = 1, nc = 1) => ({
  setNumberFormat() { return this; },
  getValues: () => Array.from({ length: nr }, (_, i) => Array.from({ length: nc }, (_, j) => cells[r + i]?.[c + j] ?? '')),
  setValues: v => v.forEach((row, i) => row.forEach((x, j) => { (cells[r + i] ||= [])[c + j] = x; })),
  clearContent: () => { for (let i = 0; i < nr; i++) for (let j = 0; j < nc; j++) if (cells[r + i]) cells[r + i][c + j] = ''; },
});
const sheet = { setName() { return sheet; }, getRange: (r, c, nr, nc) => typeof r === 'string' ? range(1, 1) : range(r, c, nr, nc), getLastRow: () => Math.max(0, cells.length - 1) };
const blob = b => ({ b: Buffer.from(b), getBytes() { return this.b; }, getDataAsString() { return this.b.toString(); } });
const g = {
  PropertiesService: { getScriptProperties: () => ({ getProperties: () => ({ ...store }), getProperty: k => store[k] ?? null, setProperty: (k, v) => { store[k] = v; }, setProperties: o => Object.assign(store, o), deleteProperty: k => delete store[k] }) },
  CacheService: { getScriptCache: () => ({ get: k => cache[k] ?? null, put: (k, v) => { cache[k] = v; } }) },
  LockService: { getScriptLock: () => ({ waitLock() {}, releaseLock() {} }) },
  ContentService: { MimeType: { JSON: 'json' }, createTextOutput: s => ({ setMimeType: () => s, toString: () => s }) },
  SpreadsheetApp: { create: () => ({ getSheets: () => [sheet], getId: () => 'SHEET1' }), openById: () => ({ getSheetByName: () => sheet }) },
  Utilities: { newBlob: s => blob(s), gzip: b => blob(gzipSync(b.b)), ungzip: b => blob(gunzipSync(b.b)), base64Encode: b => Buffer.from(b).toString('base64'),
    base64Decode: s => Buffer.from(s, 'base64'), formatDate: d => d.toISOString().slice(0, 10) },
};
const SERVE = process.argv.includes('--serve');
const code = SERVE ? readFileSync(new URL('./Secret.js', import.meta.url), 'utf8').match(/CODE = '(\w+)'/)[1] : 'ABC';
const src = readFileSync(new URL('./Code.js', import.meta.url), 'utf8') + `\nconst CODE = '${code}';\nreturn [doPost, doGet];`;
const [doPost, doGet] = new Function(...Object.keys(g), src)(...Object.values(g));
doGet();                                                          // 처음 한 번 = 시트 만들기
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
const D = '2026-10-13', OLD = '2025-01-01';
assert.equal(call({ code: 'nope', op: 'get' }).err, 'code');
const doc = (mood, j = '', d = D) => ({ date: d, exists: true, fm: { mood }, sec: { tomorrow: '', today: '', journal: j }, quote: { state: 'done' } });
assert.deepEqual(call({ op: 'mac', put: { [D]: doc(3), [OLD]: doc(1, '옛날', OLD) }, keep: [OLD, D], dates: [OLD, D], mind: [{ name: '회고' }] }).ob, {});
let r = call({ op: 'get', since: 0 });
assert.deepEqual(Object.keys(r.docs), [D]);                           // 처음엔 최근 60일만
assert.deepEqual(r.dates, [OLD, D]); assert.equal(r.mind[0].name, '회고');
assert.equal(call({ op: 'docs', dates: [OLD] }).docs[OLD].sec.journal, '옛날');   // 예전 노트는 열 때 받는다
const rev0 = r.rev;
call({ op: 'edit', date: D, fm: { mood: { v: 4, b: 3 } }, t: 1000 });
r = call({ op: 'get', since: rev0 });
assert.equal(r.docs[D].fm.mood, 4); assert.deepEqual(r.wait, { [D]: 1 }); assert.equal(r.dates, undefined);
// 맥이 아직 옛 노트를 올려도 폰 수정은 위에 남는다
let ob = call({ op: 'mac', put: { [D]: doc(3) }, keep: [OLD, D] }).ob;
assert.deepEqual(ob[D].fm.mood, { v: 4, t: 1000, b: 3 });
assert.equal(call({ op: 'docs', dates: [D] }).docs[D].fm.mood, 4);
// 맥이 가져간 뒤 폰이 또 고치면, 맥의 확인(t=1000)으로는 지워지지 않는다
call({ op: 'edit', date: D, fm: { mood: { v: 5, b: 4 } }, t: 2000 });
ob = call({ op: 'mac', done: [[D, 'fm', 'mood', 1000]] }).ob;
assert.deepEqual(ob[D].fm.mood, { v: 5, t: 2000, b: 3 });
ob = call({ op: 'mac', done: [[D, 'fm', 'mood', 2000]], put: { [D]: doc(5) } }).ob;
assert.deepEqual(ob, {}); assert.deepEqual(call({ op: 'get', since: 0 }).wait, {});
// 새 날(맥에 노트 없음)도 폰에서 쓸 수 있고, 맥이 볼트에 쓰기 전까지 지워지지 않는다
call({ op: 'edit', date: '2026-10-15', sec: { journal: { v: '폰에서 씀', b: '' } }, t: 3000 });
call({ op: 'mac', keep: [OLD, D] });
assert.equal(call({ op: 'docs', dates: ['2026-10-15'] }).docs['2026-10-15'].sec.journal, '폰에서 씀');
// 긴 글(압축이 안 되는 글)은 여러 칸으로 나눠 저장
const long = randomBytes(60000).toString('base64');
call({ op: 'mac', put: { [D]: doc(5, long) }, keep: [OLD, D, '2026-10-15'] });
assert.equal(call({ op: 'docs', dates: [D] }).docs[D].sec.journal, long);
assert.ok(cells.some(row => row && row[4]));                          // 두 번째 칸까지 씀
call({ op: 'mac', put: { [D]: doc(5) }, keep: [OLD, D, '2026-10-15'] });
assert.ok(!cells.some(row => row && row[1] === D && row[4]));         // 짧아지면 남은 칸을 비운다
// 맥에서 지운 노트는 지운다
call({ op: 'mac', done: [['2026-10-15', 'sec', 'journal', 3000]], keep: [D] });
assert.deepEqual(call({ op: 'docs', dates: [OLD, D, '2026-10-15'] }).docs[D].fm.mood, 5);
assert.deepEqual(Object.keys(call({ op: 'docs', dates: [OLD, '2026-10-15'] }).docs), []);
console.log('ok');
}
