// DAILY_NOTE_WIDGET - 데일리 노트 아이폰 위젯 (Scriptable 앱): 오늘·내일 할 일 목록 (보기만)
// 폰에 붙여넣는 건 짧은 설치 코드(폰 앱 설정 > 홈 화면 위젯)뿐이고, 그 코드가 이 파일을 받아 실행한다 → 여기만 고치면 위젯이 바뀐다
// 크기: 소형 = 오늘 · 중형 = 오늘 | 내일 · 대형 = 오늘 + 내일. 위젯 매개변수 '라이트'/'다크' 면 그 색으로 고정, 없으면 폰 설정
// 할 일은 우체통(sync/Code.js op 'widget')에서: 폰 앱에서 체크한 것은 맥이 볼트에 쓰기 전에도 보인다
// 연결 코드는 처음 한 번 Scriptable 에서 실행할 때 입력 → 이 폰 키체인에만 (코드·서버 어디에도 안 남김)

const API = 'https://script.google.com/macros/s/AKfycbwAzbhrtPtjrd8KVQuFTFXfgLmzY4Cgsk-DZlF2ur3b6a7hU_LMQOaKddSt-0O9mOIP/exec';
const APP = 'https://kimdg0116.github.io/daily-note/';
const KEY = 'daily-note-code', COLOR_KEY = 'daily-note-color';
const NO_TASKS = '없습니다😀';                                      // 템플릿이 빈 할 일 칸에 넣는 말 (server.py NO_TASKS)

const PARAM = String((typeof args !== 'undefined' && args.widgetParameter) || '');
const QP = (typeof args !== 'undefined' && args.queryParameters) || {};
// 위젯 색 = 앱 테마 색. 폰 앱 설정 > 홈 화면 위젯 > '위젯 색 맞추기'가 scriptable:///run/daily-note-widget-core?color=mint 처럼 연다
if (QP.color && /^[a-z]+$/.test(QP.color)) Keychain.set(COLOR_KEY, QP.color);
const THEME = /라이트|light/i.test(PARAM) ? 'light' : /다크|dark/i.test(PARAM) ? 'dark' : '';
const dyn = (l, d) => THEME === 'light' ? new Color(l) : THEME === 'dark' ? new Color(d)
  : Color.dynamic(new Color(l), new Color(d));
// <palettes> 도시메트리 캘린더 widget.js 와 같은 16색 (두 앱의 테마 색 토큰이 같다) [라이트, 다크] × [바탕, 글자, 흐림, 제목, 알약, 강조, 빨강, 줄]
const PALETTES = {"blue":[["#ffffff","#191919","#666666","#1428a0","#e8f1ff","#2e70ff","#fa4b50","#dbe8ff"],["#1a2233","#e9eef8","#9ba8bf","#8cbaff","#1d2c4d","#508eff","#fb6f73","#2b3750"]],"mint":[["#ffffff","#191919","#666666","#00806F","#e2f4f0","#00A08C","#fa4b50","#d3ebe5"],["#162523","#e7f2f0","#97aba7","#2BB8A5","#173531","#2BB8A5","#fb6f73","#25403b"]],"lavender":[["#ffffff","#191919","#666666","#6B5BB5","#efedf7","#8A7AD6","#fa4b50","#e6e3f2"],["#23222e","#e7e6f0","#9d9ab0","#A99CF0","#333145","#A99CF0","#fb6f73","#3b384d"]],"lilac":[["#ffffff","#191919","#666666","#86529F","#f2ecf4","#A878C8","#fa4b50","#eae2ef"],["#26222d","#e9e6ef","#a29aae","#C99BE6","#3a3143","#C99BE6","#fb6f73","#41384b"]],"indigo":[["#ffffff","#191919","#666666","#4F45A6","#ecebf5","#7166D0","#fa4b50","#e1dff0"],["#22212d","#e6e5f0","#9b99b0","#9F96EE","#313044","#9F96EE","#fb6f73","#39374c"]],"coral":[["#ffffff","#191919","#666666","#C04A36","#f8ebe9","#E8705A","#fa4b50","#f4e0dd"],["#2c2021","#eee4e6","#ac979a","#FF8A75","#452d2c","#FF8A75","#fb6f73","#4c3434"]],"apricot":[["#ffffff","#191919","#666666","#B5562B","#f7ece8","#E07B45","#fa4b50","#f2e2db"],["#2c2220","#eee6e5","#ac9b98","#FF9E6A","#45312a","#FF9E6A","#fb6f73","#4c3832"]],"rose":[["#ffffff","#191919","#666666","#BF4260","#f8eaee","#E06A84","#fa4b50","#f4dfe4"],["#2c2126","#eee5ea","#ac99a3","#FF92A8","#452f36","#FF92A8","#fb6f73","#4c363e"]],"charcoal":[["#ffffff","#191919","#666666","#3F4650","#eaebec","#6B7280","#fa4b50","#dee0e1"],["#24252a","#e8e8ed","#9fa0a9","#B8BEC8","#36383d","#B8BEC8","#fb6f73","#3e3f45"]],"bluegray":[["#ffffff","#191919","#666666","#41536B","#eaecef","#6A7C93","#fa4b50","#dfe2e6"],["#23242a","#e7e8ed","#9da0aa","#A9B9CE","#33373e","#A9B9CE","#fb6f73","#3b3e46"]],"warmgray":[["#ffffff","#191919","#666666","#504943","#ecebea","#7A7168","#fa4b50","#e1e0df"],["#262527","#e9e8eb","#a2a0a5","#C4BAB0","#393738","#C4BAB0","#fb6f73","#403e40"]],"sky":[["#ffffff","#191919","#666666","#0B5C99","#e6f1f9","#2A9BE0","#fa4b50","#d8e9f6"],["#1b242e","#e0e8f0","#8f9fb1","#5BB8F5","#243646","#5BB8F5","#fb6f73","#2b3e4e"]],"navy":[["#ffffff","#191919","#666666","#1A2D5A","#e8ebf2","#3D63B0","#fa4b50","#dbe1eb"],["#20232d","#e5e7ef","#989eaf","#8FAEE8","#2e3443","#8FAEE8","#fb6f73","#353c4b"]],"cobalt":[["#ffffff","#191919","#666666","#0B3AA8","#e6ecfc","#3B6EF5","#fa4b50","#d9e2fa"],["#1f222f","#e3e6f1","#959cb3","#7FA3FF","#2b3248","#7FA3FF","#fb6f73","#323950"]],"sage":[["#ffffff","#191919","#666666","#4A7A6A","#ebf0ef","#6E9C8B","#fa4b50","#e0e8e6"],["#212627","#e5e9eb","#99a2a5","#94C4B2","#2f3938","#94C4B2","#fb6f73","#364040"]],"teal":[["#ffffff","#191919","#666666","#0E7490","#e4f0f3","#1597B5","#fa4b50","#d6e7ec"],["#1a252c","#dfe9ef","#8ca1ad","#4CC2DE","#213841","#4CC2DE","#fb6f73","#284049"]]};
// </palettes>
const P = PALETTES[Keychain.contains(COLOR_KEY) ? Keychain.get(COLOR_KEY) : 'blue'] || PALETTES.blue;
const C = Object.fromEntries(['bg', 'fg', 'mute', 'deep', 'pill', 'acc', 'red', 'line'].map((k, i) => [k, dyn(P[0][i], P[1][i])]));
// 배경은 같은 색 두 개짜리 그라데이션으로: Scriptable 위젯의 단색 배경은 폰의 라이트/다크 전환을 따라가지 않는다
const fill = c => { const g = new LinearGradient(); g.colors = [c, c]; g.locations = [0, 1]; return g; };
const F = { head: Font.heavySystemFont(13), task: Font.semiboldSystemFont(12.5), sub: Font.mediumSystemFont(11) };
// 위젯 크기는 기종마다 다르다 (393pt 화면: 소형 158, 중형·대형 폭 338). 좌우 여백 30 을 뺀 내용 폭
const SW = Device.screenSize().width, SMALL_W = Math.floor(SW * 0.4) - 30, WIDE_W = Math.floor(SW * 0.86) - 30;

function text(stack, s, font, color) {
  const t = stack.addText(String(s));
  t.font = font; t.textColor = color; t.lineLimit = 1; t.minimumScaleFactor = 0.8;
  return t;
}

/* ── 할 일 읽기: 폰 앱 parseTasks 와 같은 규칙 (- [ ] 할 일 ✅ 날짜). 화면에는 이모지·긴 대시·마크다운 기호를 뺀다 ── */
const clean = s => s.replace(/\[\[(?:[^\]|]*\|)?([^\]]*)\]\]/g, '$1').replace(/\[([^\]]*)\]\([^)]*\)/g, '$1')
  .replace(/\*\*|__|~~|`/g, '').replace(/[—–]/g, '-').replace(/[\p{Extended_Pictographic}️‍]/gu, '').replace(/\s+/g, ' ').trim();
function parse(s) {
  if (!s || s.trim() === NO_TASKS) return [];
  return s.split('\n').map(l => {
    const m = l.match(/^(\s*)(- )?(\[([ xX])\] ?)?(.*)$/), ws = m[1];
    return { ind: Math.min(2, (ws.match(/\t/g) || []).length + Math.floor(ws.replace(/\t/g, '').length / 4)),
      box: m[3] ? (m[4] === ' ' ? ' ' : 'x') : null, text: clean(m[5].replace(/\s*✅ \d{4}-\d{2}-\d{2}\s*$/, '')) };
  }).filter(t => t.text);
}
const count = items => { const b = items.filter(t => t.box); return [b.filter(t => t.box === 'x').length, b.length]; };

/* ── 그리기 ── */
function head(stack, label, right) {
  const h = stack.addStack(); h.layoutHorizontally(); h.centerAlignContent();
  text(h, label, F.head, C.deep); h.addSpacer();
  if (right) text(h, right, F.sub, C.mute);
}
function bar(stack, items, width) {
  const [done, all] = count(items), b = stack.addStack();
  b.size = new Size(width, 4); b.cornerRadius = 2; b.backgroundGradient = fill(C.line);
  if (done) { const f = b.addStack(); f.size = new Size(Math.max(4, Math.round(width * done / all)), 4); f.cornerRadius = 2; f.backgroundGradient = fill(C.acc); }
  b.addSpacer();
}
function row(stack, t) {
  const r = stack.addStack(); r.layoutHorizontally(); r.centerAlignContent(); r.spacing = 5;
  if (t.ind) r.addSpacer(13 * t.ind);
  const done = t.box === 'x', mark = r.addStack(); mark.size = new Size(14, 14); mark.centerAlignContent();
  if (t.box) {
    const sym = SFSymbol.named(done ? 'checkmark.circle.fill' : 'circle'); sym.applyFont(Font.systemFont(13));
    const img = mark.addImage(sym.image); img.imageSize = new Size(14, 14); img.tintColor = done ? C.mute : C.acc;
  } else text(mark, '•', F.task, C.mute);                          // 체크 칸 없는 줄
  text(r, t.text, F.task, done ? C.mute : C.fg);
  r.addSpacer();
}
// room 줄 안에 보인다. 넘치면 끝낸 일을 빼고 남은 일부터, 그래도 넘치면 마지막 줄에 '+N개 더'
function list(stack, items, room) {
  const s = stack.addStack(); s.layoutVertically(); s.spacing = 4;
  if (!items.length) { text(s, '할 일 없음', F.sub, C.mute); return; }
  const open = items.filter(t => t.box !== 'x'), show = items.length <= room ? items : open.slice(0, room - 1);
  show.forEach(t => row(s, t));
  const moreOpen = open.length - show.filter(t => t.box !== 'x').length, moreDone = items.length - show.length - moreOpen;
  const more = [moreOpen ? `+${moreOpen}개 더` : '', moreDone ? `끝낸 일 ${moreDone}` : ''].filter(Boolean).join(' · ');
  if (more) { const m = s.addStack(); m.addSpacer(19); text(m, more, F.sub, C.mute); }
}
const ratio = items => { const [d, a] = count(items); return a ? `${d}/${a}` : ''; };
const stamp = d => d.stale ? `${d.hm} 기준` : '';

function buildSmall(w, d) {
  head(w, `오늘 ${d.t.md}`, stamp(d) || ratio(d.t.items)); w.addSpacer(6);
  bar(w, d.t.items, SMALL_W); w.addSpacer(6);
  list(w, d.t.items, 5); w.addSpacer();
}
function buildMedium(w, d) {
  const colW = Math.floor((WIDE_W - 21) / 2), row = w.addStack(); row.layoutHorizontally(); row.spacing = 10;
  [[`오늘 ${d.t.md}`, d.t.items, stamp(d) || ratio(d.t.items)], [`내일 ${d.m.md}`, d.m.items, String(count(d.m.items)[1] || '')]].forEach(([label, items, right], i) => {
    if (i) { const line = row.addStack(); line.size = new Size(1, Math.floor(SW * 0.4) - 30); line.backgroundGradient = fill(C.line); }
    const col = row.addStack(); col.layoutVertically(); col.size = new Size(colW, 0);
    head(col, label, right); col.addSpacer(6);
    list(col, items, 5); col.addSpacer();
  });
}
function buildLarge(w, d) {
  const N = 12, tm = Math.min(Math.max(d.m.items.length, 1), Math.max(3, N - d.t.items.length));   // 내일 칸 줄 수 (오늘이 많으면 3줄)
  head(w, `오늘 ${d.t.md}`, ratio(d.t.items)); w.addSpacer(6);
  bar(w, d.t.items, WIDE_W); w.addSpacer(6);
  list(w, d.t.items, N - tm); w.addSpacer(12);
  const line = w.addStack(); line.size = new Size(WIDE_W, 1); line.backgroundGradient = fill(C.line);
  w.addSpacer(10);
  head(w, `내일 ${d.m.md}`, String(count(d.m.items)[1] || '')); w.addSpacer(6);
  list(w, d.m.items, tm); w.addSpacer();
  const f = w.addStack(); f.addSpacer(); text(f, `${d.hm} 기준`, F.sub, C.mute);
}
function buildLock(w, d) {                                         // 잠금 화면: 남은 개수만
  const [done, all] = count(d.t.items);
  text(w, `할 일 ${all - done}개 남음`, Font.boldSystemFont(13), Color.white());
}

/* ── 불러오기 ── */
const iso = t => new Date(t - t.getTimezoneOffset() * 6e4).toISOString().slice(0, 10);
const md = t => `${t.getMonth() + 1}.${t.getDate()} ${'일월화수목금토'[t.getDay()]}`;
const hm = t => `${t.getHours()}:${String(t.getMinutes()).padStart(2, '0')}`;

async function load(code) {
  const now = new Date(), day = n => new Date(now.getFullYear(), now.getMonth(), now.getDate() + n);
  const fm = FileManager.local(), cache = fm.joinPath(fm.cacheDirectory(), 'daily-note-widget.json');
  let r, at = now, stale = false;
  try {
    const q = new Request(API);
    q.method = 'POST'; q.headers = { 'Content-Type': 'text/plain' }; q.timeoutInterval = 20;
    q.body = JSON.stringify({ code, op: 'widget', today: iso(now), yday: iso(day(-1)) });
    r = await q.loadJSON();
    if (r.err === 'code') return { auth: true };
    if (r.err) throw new Error(r.err);
    fm.writeString(cache, JSON.stringify({ date: iso(now), at: +now, r }));
  } catch (e) {                                                      // 인터넷이 안 되면 오늘 받아 둔 것
    const c = fm.fileExists(cache) ? JSON.parse(fm.readString(cache)) : null;
    if (!c || c.date !== iso(now)) return { err: String((e && e.message) || e) };
    r = c.r; at = new Date(c.at); stale = true;
  }
  const T = r.today || {}, Y = r.yday || {};
  return { stale, hm: hm(at),
    t: { md: md(now), items: parse(T.today ?? Y.tomorrow ?? '') },  // 오늘 노트가 아직 없으면 어제 노트의 내일 할 일 (노트를 만들 때 옮겨 오는 그대로)
    m: { md: md(day(1)), items: parse(T.tomorrow ?? '') } };
}

async function askCode() {
  const a = new Alert();
  a.title = '데일리 노트 위젯';
  a.message = '폰 앱 설정 > 폰 연동의 연결 코드를 넣어 주세요. 이 폰에만 저장됩니다.';
  a.addSecureTextField('연결 코드', '');
  a.addAction('저장'); a.addCancelAction('취소');
  if (await a.present() !== 0) return '';
  const code = a.textFieldValue(0).trim().toUpperCase();
  if (code) Keychain.set(KEY, code);
  return code;
}

module.exports = async () => {
  if (config.runsInApp && QP.color) {
    const a = new Alert();
    a.title = '위젯 색'; a.message = '앱 테마 색으로 맞췄습니다. 홈 화면 위젯은 다음에 새로 그릴 때 바뀝니다.'; a.addAction('확인');
    await a.present();
  }
  let code = Keychain.contains(KEY) ? Keychain.get(KEY) : '', fam = config.widgetFamily || 'medium';
  if (config.runsInApp) {                                            // 앱에서 직접 실행: 코드 입력 · 미리보기
    if (!code) code = await askCode();
    const m = new Alert();
    m.title = '데일리 노트 위젯';
    ['소형 미리보기', '중형 미리보기', '대형 미리보기', '연결 코드 다시 입력'].forEach(s => m.addAction(s));
    m.addCancelAction('닫기');
    const k = await m.presentSheet();
    if (k < 0) return Script.complete();
    if (k === 3) code = await askCode();
    fam = ['small', 'medium', 'large'][k] || 'medium';
  }
  const w = new ListWidget();
  w.backgroundGradient = fill(C.bg); w.setPadding(13, 15, 12, 15); w.url = APP;
  w.refreshAfterDate = new Date(Date.now() + 5 * 60 * 1000);          // '가장 빠르면 5분 뒤' 요청. 실제로 다시 그리는 때는 iOS 가 정한다
  const d = code ? await load(code) : { auth: true };
  if (d.auth || d.err) {
    text(w, '데일리 노트', F.head, C.deep); w.addSpacer(4);
    const t = w.addText(d.auth ? 'Scriptable 앱에서 이 위젯을 한 번 실행해 연결 코드를 넣어 주세요' : '불러오지 못했습니다: ' + d.err);
    t.font = F.sub; t.textColor = C.mute;
    w.addSpacer();
  } else if (fam.startsWith('accessory')) buildLock(w, d);
  else if (fam === 'small') buildSmall(w, d);
  else if (fam === 'large' || fam === 'extraLarge') buildLarge(w, d);
  else buildMedium(w, d);
  if (config.runsInWidget) Script.setWidget(w);
  else if (fam === 'small') await w.presentSmall();
  else if (fam === 'large') await w.presentLarge();
  else await w.presentMedium();
  Script.complete();
};
// 목록에서 이 파일(daily-note-widget-core)을 직접 눌러도 돈다. 설치 코드가 불러올 때는 Script.name() 이 설치 코드 이름이라 두 번 돌지 않는다
if (Script.name() === 'daily-note-widget-core') module.exports();
