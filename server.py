"""데일리 노트 - 맥에서만 도는 작은 서버.

볼트의 데일리 노트(04 Life/Planner/Daily/YYYY-MM-DD(요일).md)를 앱 화면으로 쓰고 고친다.
- 칸은 거의 다 frontmatter 값이라(meta-bind) 그 키만 바꾸고, 할 일·공부·Journal 은 본문 그 자리만 바꾼다
- 노트가 없는 날은 쓰기 시작할 때 데일리 템플릿 그대로 만든다 (Templater 가 하던 일: 날짜 링크, 어제 Tomorrow's Tasks, 오늘의 명언)
- 새 명언은 Claude Code 를 `claude -p "/명언 <날짜>"` 로 불러 번역·저자 노트까지 정리한다

    python3 server.py          서버만 (127.0.0.1:8749). 폰 연동(sync/Secret.js 가 있으면)도 같이 돈다
    VAULT=<사본 볼트> CLAUDE=<가짜 claude> [SYNC_URL=<가짜 연동 서버>] python3 server.py    시험용 (사본 볼트면 진짜 연동 서버로는 안 보낸다)
"""
import base64, gzip, hashlib, json, os, re, shutil, subprocess, tempfile, threading, time, unicodedata, urllib.request
from datetime import date, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs, quote

import yaml

PORT = int(os.environ.get('PORT') or 8749)   # 시험은 PORT=8750 + 사본 볼트 (진짜 서버가 8749 를 쓰는 중이라)
HERE = os.path.dirname(os.path.abspath(__file__))
VAULT = os.environ.get('VAULT') or os.path.expanduser('~/Obsidian_Dongkyu')
DAILY_REL = '04 Life/Planner/Daily'
DAILY = os.path.join(VAULT, DAILY_REL)
TEMPLATE = os.path.join(VAULT, '90 System', 'Templates', 'Daily Note Template.md')
AUTHORS_REL = '04 Life/명언/저자'
ATTACH = os.path.join(VAULT, '90 System', '첨부파일')
WD = '월화수목금토일'
DATE = re.compile(r'^\d{4}-\d{2}-\d{2}$')
KEY = re.compile(r'^[\w가-힣]+$')
NO_TASKS = '없습니다😀'
FAILED = '오늘의 명언을 불러오지 못했습니다. 나중에 다시 시도해 주세요.', 'ZenQuotes 연결 실패'
ENV = dict(os.environ, PATH=':'.join([
    os.path.expanduser('~/.local/bin'), '/Library/Frameworks/Python.framework/Versions/3.14/bin',
    '/opt/homebrew/bin', '/usr/local/bin', os.environ.get('PATH', '/usr/bin:/bin')]))
CLAUDE = os.environ.get('CLAUDE') or shutil.which('claude', path=ENV['PATH']) or os.path.expanduser('~/.local/bin/claude')
# /명언 에 필요한 것만: 노트 읽고 쓰기, 저자·출처 조사, 초상 받기(portrait.py)
TOOLS = 'Read Edit Write Glob Grep WebSearch WebFetch Bash(python3:*) Bash(ls:*)'
FILE_LOCK = threading.Lock()
STATIC = {'/cm.js': 'text/javascript; charset=utf-8', '/manifest.webmanifest': 'application/manifest+json',
          '/icon-192.png': 'image/png', '/icon-512.png': 'image/png', '/apple-touch-icon.png': 'image/png'}


# ── 날짜 · 파일 ───────────────────────────────────────────

def day(d):
    return date.fromisoformat(d)


def fname(d):
    return f'{d.isoformat()}({WD[d.weekday()]})'


def path(d):
    return os.path.join(DAILY, fname(d) + '.md')


def week_key(d):
    """moment ko 로케일의 gggg-[W]ww: 주는 일요일 시작, 1월 1일이 든 주가 1주"""
    sun = d - timedelta(days=(d.weekday() + 1) % 7)
    wy = (sun + timedelta(days=6)).year
    j1 = date(wy, 1, 1)
    return wy, (sun - (j1 - timedelta(days=(j1.weekday() + 1) % 7))).days // 7 + 1


def write(p, text):
    with open(p + '.tmp', 'w', encoding='utf-8') as f:
        f.write(text)
    os.replace(p + '.tmp', p)


# ── frontmatter: 바꾼 키의 줄만 갈아 끼운다 ─────────────────

FM = re.compile(r'^---\n(.*?)\n---\n', re.S)
TOP = re.compile(r'^[^\s#-][^:]*:')


class Dumper(yaml.SafeDumper):
    pass


# 여러 줄 글은 meta-bind 처럼 `|-` 블록으로
Dumper.add_representer(str, lambda d, s: d.represent_scalar('tag:yaml.org,2002:str', s, style='|' if '\n' in s else None))


def split(text):
    m = FM.match(text)
    return (m.group(1), text[m.end():]) if m else ('', text)


def fm_set(fm, key, val):
    lines = fm.split('\n') if fm else []
    new = [f'{key}:'] if val is None else \
        yaml.dump({key: val}, Dumper=Dumper, allow_unicode=True, sort_keys=False, width=10 ** 9).rstrip('\n').split('\n')
    if new[-1] == '...':                  # 끝에 빈 줄이 있는 글(|+)이면 yaml 이 문서 끝 표시를 붙인다 → 뒤 키가 다 깨진다
        new.pop()
    i = next((k for k, l in enumerate(lines) if re.match(rf'^{re.escape(key)}:(\s|$)', l)), None)
    if i is None:
        return '\n'.join(lines + new)
    j = i + 1
    while j < len(lines) and not TOP.match(lines[j]):
        j += 1
    lines[i:j] = new
    return '\n'.join(lines)


# ── 본문 칸: 제목 줄 ~ 다음 칸 시작 사이만 ────────────────────

SECS = {
    'tomorrow': (lambda l: l.strip() == "### Tomorrow's Tasks", lambda l: l.startswith("### Today's Tasks")),
    'today': (lambda l: l.strip() == "### Today's Tasks", lambda l: l.startswith(('> [!', '### ', '#### '))),
    'study': (lambda l: l.startswith('> [!note]') and '공부' in l, lambda l: not l.startswith('>')),
    'journal': (lambda l: l.startswith('### ') and 'Journal' in l, lambda l: l.startswith(('#### #', '> [!question]'))),
}


def sec_span(lines, k):
    head, stop = SECS[k]
    s = next((i for i, l in enumerate(lines) if head(l)), None)
    if s is None:
        return None
    e = next((i for i in range(s + 1, len(lines)) if stop(lines[i])), None)
    return None if e is None else (s, e)


def sec_get(lines, k):
    sp = sec_span(lines, k)
    if not sp:
        return None
    body = lines[sp[0] + 1:sp[1]]
    if k == 'study':
        body = [re.sub(r'^> ?', '', l) for l in body]
    text = '\n'.join(body).strip('\n')
    return '' if k == 'today' and text.strip() == NO_TASKS else text


def sec_set(lines, k, text):
    sp = sec_span(lines, k)
    if not sp:
        return lines
    text = text.replace('\r', '').strip('\n')
    if k == 'study':
        new = ['> ' + l if l else '>' for l in text.split('\n')] if text.strip() else ['> ']
    else:
        new = (text or (NO_TASKS if k == 'today' else '')).split('\n') + ['']
        if new == ['', '']:
            new = ['']
    return lines[:sp[0] + 1] + new + lines[sp[1]:]


# ── 명언 칸 (읽기만. 고치는 건 /명언 스킬) ──────────────────

def plain(s):
    return re.sub(r'\[\[(?:[^\]|]*\|)?([^\]]*)\]\]', r'\1', s).replace('**', '').strip()


def quote_span(lines):
    i = next((k for k, l in enumerate(lines) if re.match(r'^>\s?\[!quote\]', l)), None)
    if i is None:
        return None
    j = i + 1
    while j < len(lines) and lines[j].startswith('>'):
        j += 1
    return i, j


def quote_get(lines):
    sp = quote_span(lines)
    if not sp:
        return {'state': 'none'}
    head = plain(re.sub(r'^>\s?\[!quote\][+-]?', '', lines[sp[0]]))           # 예전 노트는 명언이 제목 줄에
    text, author, flag = [head] if head and head.lower() != 'quote of the day' else [], '', ''
    for l in lines[sp[0] + 1:sp[1]]:
        s = l[1:].strip()
        if not author and re.match(r'^[—–-]\s', s):
            author = s[1:].strip()
        elif s.startswith(('⚠️', 'ℹ️')):
            flag = plain(s)
        elif s and not author:
            text.append(s)
    link = ''
    for l in lines[sp[1]:]:
        m = re.search(r'이 저자 \[\[([^\]|#]+)', l)
        if m:
            link = m.group(1).strip()
    # 번역: [!info] 콜아웃의 첫 한글 줄 (예전 노트는 콜아웃 없이 바로 아래 인용 줄에)
    j = next((k for k in range(sp[1], len(lines)) if re.match(r'^>\s?\[!info\]', lines[k])), None)
    if j is None:
        j = sp[1]
        while j < len(lines) and not lines[j].strip():
            j += 1
    ko = ''
    while j < len(lines) and lines[j].startswith('>') and not ko:
        k = plain(re.sub(r'^>\s?(\[!\w+\][+-]?)?\s*(- )?', '', lines[j])).strip('"“” ')
        ko = '' if not k or 'INPUT[' in k or re.match(r'^[A-Za-z]', k) else k
        j += 1
    failed = not author or author in (FAILED[1], 'zenquotes.io')
    return {'text': plain(' '.join(text)), 'author': author, 'ko': ko, 'flag': flag, 'link': link,
            'toggle': any('INPUT[toggle:quote_체크]' in l for l in lines),      # 모으기 토글이 생긴(2026-08-09) 뒤 노트
            'state': 'failed' if failed else 'done' if link else 'todo'}


# ── 명언 모음: 모으기를 켠 명언(토글 전 노트는 전부) + 별(📜 명언 모음 노트의 favorites) ──

MOC = os.path.join(VAULT, '04 Life', '명언', '📜 명언 모음.md')   # 2026-10-23 볼트 정리로 명언 폴더 안으로 옮겨짐
FAV = '_fav'                          # 폰에서 별을 바꾸면 그 날짜 수정에 이 키로 실려 온다 (노트에는 안 씀)


def fav_get(fm):
    favs = (yaml.safe_load(fm) or {}).get('favorites') or []
    return [d for d in (str(x).strip('[]')[:10] for x in favs) if DATE.match(d)]


def fav_set(d, on):
    with FILE_LOCK:
        fm, body = split(open(MOC, encoding='utf-8').read())
        favs = [x for x in fav_get(fm) if x != d] + ([d] if on else [])
        block = 'favorites:' + (''.join(f'\n  - "[[{fname(day(x))}]]"' for x in favs) if favs else ' []')
        fm, n = re.subn(r'^favorites:.*(?:\n[ \t]*-.*)*', lambda m: block, fm, count=1, flags=re.M)
        write(MOC, f'---\n{fm if n else fm + chr(10) + block}\n---\n{body}')


def quote_list():
    """모음 후보 전부 (화면이 모으기 켬·토글 여부로 거른다 - 폰은 자기가 고친 값으로)"""
    try:
        moc = open(MOC, encoding='utf-8').read()
    except OSError:
        moc = '---\n---\n'
    ko_fb = dict(re.findall(r"'(\d{4}-\d{2}-\d{2})\(.\)': '([^']+)'", moc))   # 명언 모음 노트가 대신 넣은 번역 (예전 노트 7개)
    out = []
    for d in note_dates():
        fm, body = split(open(path(day(d)), encoding='utf-8').read())
        q = quote_get(body.split('\n'))
        if q['state'] in ('done', 'todo') and q['text']:
            out.append({'date': d, 'text': q['text'], 'author': q['author'], 'ko': q['ko'] or ko_fb.get(d, ''), 'flag': q['flag'],
                        'toggle': q['toggle'], 'on': bool(re.search(r'^quote_체크:\s*true\s*$', fm, re.M))})
    return {'list': out, 'favs': fav_get(split(moc)[0])}


# ── 일정: 04 Life/Planner/일정.md 의 `- [ ] YYYY-MM-DD 이름` 줄. 앱은 데일리 노트 위 카드에 D-day 와 함께 보인다 ──
# 날짜 없이 `- [ ] 이름 ➕ 넣은 날` 이면 기한 없는 일정 (가능한 빨리, 넣은 지 며칠째인지 보인다)
# 다른 줄은 그대로 두고 체크·추가·고치기(날짜·이름)·지우기(앱에서 옆으로 밀어서)만 한다

PLANS = os.path.join(VAULT, '04 Life', 'Planner', '일정.md')
PLAN = re.compile(r'^(\s*[-*] \[)([ xX])\] (?:(\d{4}-\d{2}-\d{2})\s+)?(.+?)\s*$')
DONE_AT = re.compile(r'\s*✅ \d{4}-\d{2}-\d{2}')     # 옵시디언 Tasks 플러그인이 체크할 때 붙이는 날짜
ADDED = re.compile(r'\s*➕ (\d{4}-\d{2}-\d{2})')     # 넣은 날 (Tasks 플러그인의 만든 날 표기)


def plan_items(lines):
    """[(줄 번호, {d: 날짜 또는 '' (기한 없음), n: 이름, x: 끝냄, a: 넣은 날 또는 ''})]"""
    out = []
    for i, l in enumerate(lines):
        m = PLAN.match(l)
        n = m and ' '.join(ADDED.sub('', DONE_AT.sub('', m.group(4))).split())
        if n:
            a = ADDED.search(m.group(4))
            out.append((i, {'d': m.group(3) or '', 'n': n, 'x': m.group(2) != ' ', 'a': a.group(1) if a else ''}))
    return out


def plan_lines():
    try:
        text = open(PLANS, encoding='utf-8').read().rstrip('\n')
    except OSError:
        return []
    return text.split('\n') if text else []


def plan_list():
    return [p for _, p in plan_items(plan_lines())]


def real_date(s):
    try:
        return bool(DATE.match(s)) and bool(day(s))
    except ValueError:
        return False


def plan_ok(o):
    """d 는 날짜 또는 '' (기한 없음), a(넣은 날)는 있으면 날짜. edit 은 nd·nn = 새 날짜·이름"""
    day_ok = lambda v: v == '' or real_date(str(v))
    return isinstance(o, dict) and o.get('act') in ('add', 'toggle', 'del', 'edit') and isinstance(o.get('n'), str) \
        and day_ok(o.get('d')) and (not o.get('a') or real_date(str(o['a']))) \
        and (o['act'] != 'toggle' or isinstance(o.get('on'), bool)) \
        and (o['act'] != 'edit' or (day_ok(o.get('nd')) and isinstance(o.get('nn'), str)))


def plan_apply(ops):
    """폰·맥에서 온 일정 바꾸기를 노트에 (같은 날짜·이름이 이미 있으면 추가는 건너뛴다 → 두 번 와도 한 번만)"""
    with FILE_LOCK:
        lines = plan_lines()
        old = list(lines)
        for o in filter(plan_ok, ops):
            n, items = ' '.join(o['n'].split())[:200], plan_items(lines)
            hit = next((i for i, p in items if p['d'] == o['d'] and p['n'] == n), None)
            if o['act'] == 'add' and n and hit is None:          # 넣은 날은 폰에서 넣은 날 (맥이 늦게 받아도)
                lines.append(f'- [ ] {o["d"]} {n}' if o['d'] else f'- [ ] {n} ➕ {o.get("a") or date.today().isoformat()}')
            elif o['act'] == 'toggle' and hit is not None:
                m = PLAN.match(lines[hit])
                line = m.group(1) + ('x' if o['on'] else ' ') + lines[hit][m.end(2):]
                if o['on'] and m.group(2) == ' ' and not DONE_AT.search(line):   # 끝낸 날 (Tasks 플러그인처럼) → 바탕화면 위젯이 그날은 체크된 채로 둔다
                    line = line.rstrip() + f' ✅ {date.today().isoformat()}'
                lines[hit] = line if o['on'] else DONE_AT.sub('', line)
            elif o['act'] == 'del' and hit is not None:           # 그 줄만 (없으면 이미 지운 것)
                del lines[hit]
            elif o['act'] == 'edit' and hit is not None:          # 날짜·이름만 바꾸고 체크·넣은 날·끝낸 날은 둔다
                nd, nn = o['nd'], ' '.join(o['nn'].split())[:200]
                if nn and not any(p['d'] == nd and p['n'] == nn for i, p in items if i != hit):   # 다른 일정과 같아지면 안 바꾼다
                    m, a = PLAN.match(lines[hit]), dict(items)[hit]['a'] or ('' if nd else o.get('a') or date.today().isoformat())
                    done = DONE_AT.search(m.group(4))
                    lines[hit] = f'{m.group(1)}{m.group(2)}] ' + (f'{nd} ' if nd else '') + nn + (f' ➕ {a}' if a else '') + (done.group(0) if done else '')
        if lines != old:
            os.makedirs(os.path.dirname(PLANS), exist_ok=True)
            write(PLANS, '\n'.join(lines) + '\n')
        return [p for _, p in plan_items(lines)]


def fetch_quote():
    try:
        r = urllib.request.Request('https://zenquotes.io/api/random', headers={'User-Agent': 'Mozilla/5.0'})
        x = json.load(urllib.request.urlopen(r, timeout=2.5))[0]
        q, a = x['q'].strip(), x['a'].strip()
        if not q or a == 'zenquotes.io':          # 너무 자주 부르면 '요청이 많다'는 글이 저자 zenquotes.io 로 온다
            raise ValueError(q)
    except Exception as e:
        print('명언 받기 실패:', e, flush=True)
        q, a = FAILED
    return f'>[!quote]\n>{q}\n>— {a}'


def author_get(name, qtext):
    """저자 노트에서 화면에 보일 것만: 사진, 이 명언의 출처 줄, 기본 정보 몇 줄"""
    folder = os.path.join(VAULT, AUTHORS_REL)
    want = unicodedata.normalize('NFC', name + '.md')
    f = next((f for f in (os.listdir(folder) if os.path.isdir(folder) else []) if unicodedata.normalize('NFC', f) == want), None)
    if not f:
        return None
    text = open(os.path.join(folder, f), encoding='utf-8').read()
    photo = re.search(r'!\[\[([^\]|]+\.(?:jpe?g|png|webp|gif))', text, re.I)
    at = max(text.find(qtext[:25]), 0) if qtext else 0
    src = re.search(r'^- 출처:\s*(.+)$', text[at:], re.M) or re.search(r'^- 출처:\s*(.+)$', text, re.M)
    info = re.search(r'^## 기본 정보\n(.*?)(?=^## |\Z)', text, re.S | re.M)
    bullets = [plain(l[2:]) for l in (info.group(1).split('\n') if info else []) if l.startswith('- ')][:4]
    return {'name': name, 'photo': photo.group(1) if photo else '', 'src': plain(src.group(1)) if src else '', 'info': bullets}


# ── 템플릿: Templater 코드 4개를 앱이 대신 채운다 ─────────────

def carried(d):
    """어제 노트의 Tomorrow's Tasks (템플릿 스크립트와 같은 방식)"""
    try:
        c = open(path(d - timedelta(days=1)), encoding='utf-8').read()
    except OSError:
        return NO_TASKS
    a, b = "## Tomorrow's Tasks", "## Today's Tasks"
    if a not in c:
        return NO_TASKS
    i = c.index(a) + len(a)
    j = c.find(b, i)
    s = re.sub(r'^[#\s]+', '', re.sub(r'[#\s]+$', '', c[i:j if j >= 0 else None]).strip()).strip()
    return s or NO_TASKS


def nav(d):
    wy, wk = week_key(d)
    p, n = d - timedelta(days=1), d + timedelta(days=1)
    return (f'〈 [[{d.year}|{d.year}년]] / [[{d:%Y-%m}|{d:%m}월]] / [[{wy}-W{wk:02d}|{wk:02d}주]] 〉\n'
            f'《 [[{fname(p)}]] | [[{fname(d)}]] | [[{fname(n)}]] 》')


def render(d, quote_md):
    def block(m):
        code = m.group(1)
        if 'tp.file.title.slice(0,10)' in code:
            return d.isoformat()
        if 'currentMoment' in code:
            return nav(d)
        if "Tomorrow's Tasks" in code:
            return carried(d)
        if 'randomQuote' in code:
            return quote_md
        raise ValueError('데일리 템플릿에 앱이 모르는 코드가 생겼어요: ' + ' '.join(code.split())[:60])
    return re.sub(r'<%[*_-]?(.*?)[-_]?%>', block, open(TEMPLATE, encoding='utf-8').read(), flags=re.S)


def mind_form(text=None):
    """템플릿의 Journal 아래 마음 기록 칸들을 그대로 읽어 화면 양식으로 (템플릿을 고치면 앱도 따라간다)"""
    lines = (text if text is not None else open(TEMPLATE, encoding='utf-8').read()).split('\n')
    start = next((i for i, l in enumerate(lines) if l.startswith('### ') and 'Journal' in l), len(lines))
    out, cur, ask, tip = [], None, [], None
    for l in lines[start + 1:]:
        if 'randomQuote' in l or re.match(r'^>\s?\[!quote\]', l):
            break
        if not l.startswith('>'):
            tip = None
        if l.strip() == '---':
            out.append({'sep': True})
        elif m := re.match(r'^#### #(.+)', l):
            cur, ask = {'name': m.group(1).strip(), 'check': '', 'items': []}, []
            out.append(cur)
        elif not cur:
            continue
        elif m := re.match(r'^-\s*`INPUT\[toggle:([^\]]+)\]`\s*(.*)', l):
            if ask:
                cur['items'].append({'ask': ask})
                ask = []
            cur['items'].append({'toggle': m.group(1), 'label': m.group(2).strip()})
        elif m := re.match(r'^`INPUT\[toggle:([^\]]+)\]`', l):
            cur['check'] = cur['check'] or m.group(1)
        elif m := re.search(r'INPUT\[editor:([^\]]+)\]', l):
            cur['items'].append({'field': m.group(1), 'ask': ask})
            ask = []
        elif m := re.match(r'^(?:(.+?) :: )?\*\*(.+)\*\*\s*$', l):
            ask.append({'label': m.group(1) or '', 'text': m.group(2)})
        elif m := re.match(r'^>\s?\[!\w+\]([+-]?)\s*(.*)', l):            # 질문 바로 아래 콜아웃 = 그 질문의 참고 (앱에서는 접히는 목록)
            tip = {'title': plain(m.group(2)), 'open': m.group(1) != '-', 'items': []}
            if ask:
                ask[-1]['tip'] = tip
        elif tip and (s := plain(re.sub(r'^>\s?(?:[-*]\s+)?', '', l))):
            tip['items'].append(s)
    return out


def mind_old(body, f):
    """템플릿에서 빠진 칸에 쓴 답 (그 노트 본문의 양식으로 읽어, 예전 답이 앱에서도 보이게)"""
    now = {m['name'] for m in mind_form() if 'name' in m}
    return [m for m in mind_form(body) if 'name' in m and m['name'] not in now
            and any(f.get(i.get('field')) or f.get(i.get('toggle')) is True for i in m['items'])]


# ── 읽기 · 저장 ───────────────────────────────────────────

def ok_fm(k, v):
    return bool(KEY.match(k)) and k not in ('date', 'type', 'tags') and (v is None or isinstance(v, (str, bool, int)))


def ok_sec(k, v):
    return k in SECS and isinstance(v, str)


def note_dates():
    names = os.listdir(DAILY) if os.path.isdir(DAILY) else []
    return sorted(n[:10] for n in names if DATE.match(n[:10]) and n.endswith('.md'))


def read_day(d):
    p = path(d)
    exists = os.path.exists(p)
    text = open(p, encoding='utf-8').read() if exists else render(d, '')
    fm, body = split(text)
    lines = body.split('\n')
    q = quote_get(lines) if exists else {'state': 'new'}
    wy, wk = week_key(d)
    f = yaml.safe_load(fm) or {}
    return {'date': d.isoformat(), 'name': fname(d), 'exists': exists, 'week': wk,
            'mtime': os.path.getmtime(p) if exists else 0,
            'fm': f, 'sec': {k: sec_get(lines, k) for k in SECS}, 'mind_old': mind_old(body, f),
            'quote': q, 'author': author_get(q['link'], q.get('text', '')) if q.get('link') else None}


def save_day(d, fmc, secc):
    with FILE_LOCK:
        p = path(d)
        created = not os.path.exists(p)
        text = render(d, fetch_quote()) if created else open(p, encoding='utf-8').read()
        fm, body = split(text)
        for k, v in fmc.items():
            fm = fm_set(fm, k, v)
        lines = body.split('\n')
        for k, v in secc.items():
            lines = sec_set(lines, k, v)
        os.makedirs(DAILY, exist_ok=True)
        write(p, f'---\n{fm}\n---\n' + '\n'.join(lines))
        return created, os.path.getmtime(p)


def requote(d):
    """명언을 못 받은 날만 다시 받는다"""
    with FILE_LOCK:
        p = path(d)
        fm, body = split(open(p, encoding='utf-8').read())
        lines = body.split('\n')
        sp = quote_span(lines)
        if not sp or quote_get(lines)['state'] != 'failed':
            return False
        new = fetch_quote()
        if FAILED[1] in new:
            return False
        lines[sp[0]:sp[1]] = new.split('\n')
        write(p, f'---\n{fm}\n---\n' + '\n'.join(lines))
        return True


# ── /명언 작업 (한 번에 하나) ──────────────────────────────

JOB = {'state': 'idle'}
TRIED = set()                 # 오늘 노트 자동 정리는 날짜마다 한 번만 (실패해도 버튼으로 다시)
LABEL = {'Read': '읽는 중', 'Edit': '노트에 쓰는 중', 'Write': '노트에 쓰는 중', 'Glob': '파일 찾는 중',
         'Grep': '찾는 중', 'WebSearch': '검색', 'WebFetch': '자료 읽는 중', 'Bash': '실행'}


def start_quote(d):
    if JOB.get('state') == 'running':
        return False
    TRIED.add(d)
    JOB.clear()
    JOB.update(state='running', date=d, started=time.time(), steps=[], result='')
    threading.Thread(target=run_quote, args=(d,), daemon=True).start()
    return True


def run_quote(d):
    cmd = [CLAUDE, '-p', f'/명언 {d}', '--output-format', 'stream-json', '--verbose',
           '--permission-mode', 'acceptEdits', '--allowedTools', TOOLS]
    try:
        p = subprocess.Popen(cmd, cwd=VAULT, env=ENV, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    except OSError as e:
        JOB.update(state='error', result=f'Claude Code 를 실행하지 못했어요: {e}')
        return

    def step(t):
        t = (t or '').strip()
        if t and (not JOB['steps'] or JOB['steps'][-1] != t):
            JOB['steps'] = (JOB['steps'] + [t])[-40:]

    tail = []
    for line in p.stdout:
        tail = (tail + [line])[-20:]
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        typ = ev.get('type')
        if typ == 'system' and ev.get('subtype') == 'task_summary':
            step(ev.get('detail'))
        elif typ == 'assistant':
            for c in ev.get('message', {}).get('content', []):
                if c.get('type') == 'tool_use':
                    inp = c.get('input') or {}
                    what = inp.get('description') or os.path.basename(inp.get('file_path', '') or '') or inp.get('query', '') or inp.get('url', '')
                    step(f"{LABEL.get(c.get('name'), c.get('name'))} {what}")
        elif typ == 'result':
            JOB['result'] = ev.get('result') or ''
            JOB['is_error'] = bool(ev.get('is_error'))
    p.wait()
    ok = p.returncode == 0 and not JOB.get('is_error')
    JOB.update(state='done' if ok else 'error', ended=time.time())
    if not ok:
        JOB['result'] = JOB.get('result') or ''.join(tail)[-1500:] or f'종료 코드 {p.returncode}'
    SYNC_WAKE.set()                   # 번역·저자가 붙은 노트를 폰에도


# ── 폰 연동: Apps Script 가 우체통(전달만). 맥은 바뀐 노트를 보내고(폰이 처음엔 전부 받아 감), 폰에서 고친 칸을 받아 볼트에 쓴다 ─────

SYNC_URL = os.environ.get('SYNC_URL') or 'https://script.google.com/macros/s/AKfycbwAzbhrtPtjrd8KVQuFTFXfgLmzY4Cgsk-DZlF2ur3b6a7hU_LMQOaKddSt-0O9mOIP/exec'
SYNC_STATE = os.path.join(VAULT, '.daily-sync.json') if os.environ.get('VAULT') else os.path.join(HERE, 'sync', 'state.json')   # 올린 노트의 mtime·받은 수정 확인 (git 제외)
SYNC = {'at': 0, 'err': ''}
BATCH_N, BATCH_BYTES = 80, 250_000     # 폰이 노트를 처음 받아 갈 때 한 묶음 (우체통 상자 300KB 안에)
RPUT_BYTES = 45_000                    # 폰이 달라는 읽을 글 본문을 한 번에 이만큼 (우체통 본문 상자 90KB 안에, 압축 크기)
IPUT_BYTES = 2_000_000                 # 폰이 달라는 그림을 한 번에 이만큼 (우체통 캐시로, data URL 글자 수)
SYNC_WAKE = threading.Event()


def sync_code():
    try:
        return re.search(r"CODE = '(\w+)'", open(os.path.join(HERE, 'sync', 'Secret.js'), encoding='utf-8').read()).group(1)
    except (OSError, AttributeError):
        return ''


def phone_doc(d):
    n = read_day(d)
    if n['author']:
        n['author'].pop('photo', None)    # 사진은 볼트 안에만
    return json.loads(json.dumps(n, default=str))


def same(a, b):
    return ('' if a is None else a) == ('' if b is None else b)


def pick(cur, mtime_ms, o):
    """폰에서 고친 칸 중 볼트에 쓸 것. 맥에서도 그 칸을 고쳤으면(폰이 본 값 b 와 다르면) 나중에 고친 쪽이 이긴다"""
    out, done = {'fm': {}, 'sec': {}}, []
    for part, ok in (('fm', ok_fm), ('sec', ok_sec)):
        for k, e in (o.get(part) or {}).items():
            done.append([part, k, e.get('t')])
            v, now = e.get('v'), cur[part].get(k)
            if ok(k, v) and not same(now, v) and (same(now, e.get('b')) or (e.get('t') or 0) > mtime_ms):
                out[part][k] = v
    return out['fm'], out['sec'], done


def sync_post(body):
    r = urllib.request.Request(SYNC_URL, data=json.dumps(body, ensure_ascii=False, default=str).encode(), headers={'Content-Type': 'text/plain'})
    return json.load(urllib.request.urlopen(r, timeout=40))


def sync_once(code):
    st = load_json(SYNC_STATE, {})
    dates = note_dates()
    mt = {d: os.path.getmtime(path(day(d))) for d in dates}
    mind, quotes, plans = mind_form(), quote_list(), plan_list()
    dh, mh, qh, ph = (hashlib.sha1(json.dumps(x, ensure_ascii=False).encode()).hexdigest() for x in (dates, mind, quotes, plans))
    if st.get('fmt') != 3:                # 노트 읽는 법이 바뀌었다(mind_old) → 폰 사본도 한 번 다시 보낸다
        st.update(up={d: 0 for d in mt} if 'up' in st else dict(mt), fmt=3)
    up = st.setdefault('up', dict(mt))    # 처음엔 지금 상태를 기준으로만 (노트 내용은 폰이 '다시 받기'로 가져간다)
    changed = [d for d in dates if up.get(d) != mt[d]][:40]           # 맥에서 바뀐 노트 (한 번에 40개까지)
    put = {d: phone_doc(day(d)) for d in changed}
    body = {'code': code, 'op': 'mac', 'done': st.get('done', []), 'pdone': st.get('pdone', []), 'put': put}
    want = st.get('want')
    if want and not want.get('done') and want.get('seen', 0) >= want.get('sent', 0):   # 폰이 앞 묶음을 받았으면 다음 묶음
        rest, batch, size = [d for d in dates if d > want.get('from', '')], [], 0
        for d in rest:                    # 날짜순으로 한 묶음씩
            put[d] = put.get(d) or phone_doc(day(d))
            batch.append(d)
            size += len(json.dumps(put[d], ensure_ascii=False).encode())
            if size > BATCH_BYTES or len(batch) >= BATCH_N:
                break
        body['resync'] = {'to': batch[-1] if batch else want.get('from', ''), 'done': len(batch) == len(rest)}
    if st.get('dh') != dh:
        body['dates'] = dates
    if st.get('mh') != mh:
        body['mind'] = mind
    if st.get('qh') != qh:
        body['quotes'] = quotes
    if st.get('ph') != ph:
        body['plans'] = plans
    # 읽을 글: 목록·테마는 바뀔 때만, 본문은 폰이 달라는 것만 (압축 크기로 RPUT_BYTES 까지), 폰에서 누른 읽음을 노트에 쓴 확인
    reads, theme = read_items(), theme_css()
    rh, th = (hashlib.sha1(json.dumps(x, ensure_ascii=False).encode()).hexdigest() for x in (reads, theme))
    if st.get('rh') != rh:
        body['reads'] = reads
    if st.get('th') != th:
        body['theme'] = theme
    rput, rqdone, size = {}, [], 0
    for rel in st.get('rq') or []:
        try:
            doc = read_doc(rel)
        except (OSError, ValueError, yaml.YAMLError):
            rqdone.append(rel)                    # 없는 노트는 요청에서 뺀다
            continue
        n = len(base64.b64encode(gzip.compress(json.dumps(doc, ensure_ascii=False).encode())))
        if rput and size + n > RPUT_BYTES:
            break
        rput[hashlib.sha1(doc['rel'].encode()).hexdigest()[:12]] = doc
        rqdone.append(rel)
        size += n
    iput, iqdone, isize = {}, [], 0                                     # 폰이 달라는 그림: 줄여서 캐시로 (없는 그림은 요청에서 뺀다)
    for name in st.get('iq') or []:
        try:
            url = phone_img(name)
        except (OSError, ValueError, subprocess.SubprocessError):
            url = None
        if url and iput and isize + len(url) > IPUT_BYTES:
            break
        if url:
            iput[name] = url
            isize += len(url)
        iqdone.append(name)
    body.update(rput=rput, rqdone=rqdone, rdone=st.get('rdone', []), iput=iput, iqdone=iqdone)
    r = sync_post(body)
    if r.get('err'):
        raise RuntimeError('연결 코드가 맞지 않아요' if r['err'] == 'code' else r['err'])
    up.update({d: mt[d] for d in put})
    st.update(done=[], pdone=[], dh=dh, mh=mh, qh=qh, ph=ph, want=r.get('want'), rh=rh, th=th, rdone=[],
              rq=[x for x in (r.get('rq') or []) if isinstance(x, str)][:60],
              iq=[x for x in (r.get('iq') or []) if isinstance(x, str)][:200])
    for rel, m in (r.get('rob') or {}).items():                         # 폰에서 누른 읽음 → 노트에, 다음 번에 받았다고 알린다
        try:
            read_mark(rel, bool(m.get('on')), str(m.get('memo') or ''), m.get('day'))
        except (OSError, ValueError) as e:
            print('폰 읽음 못 씀:', rel, e, flush=True)             # 없는 노트 등은 확인만 하고 버린다
        st['rdone'].append([rel, m.get('t')])
    po = [o for o in (r.get('po') or []) if isinstance(o, dict)]      # 폰에서 바꾼 일정 → 일정 노트, 다음 번에 받았다고 알린다
    if po:
        plan_apply(po)
        st['pdone'] = [o.get('id') for o in po]
    for d, o in (r.get('ob') or {}).items():
        if not DATE.match(d):
            continue
        fav = (o.get('fm') or {}).pop(FAV, None)
        if fav:
            if isinstance(fav.get('v'), bool) and os.path.exists(MOC):
                fav_set(d, fav['v'])
            st['done'].append([d, 'fm', FAV, fav.get('t')])
        cur = read_day(day(d))
        fmc, secc, acks = pick(cur, cur['mtime'] * 1000, o)
        if fmc or secc:
            created, _ = save_day(day(d), fmc, secc)
            if created:
                start_quote(d)
        st['done'] += [[d] + a for a in acks]
    save_json(SYNC_STATE, st)
    # 곧바로 한 번 더: 볼트에 쓴 걸 올리고 받았다고 알릴 때, 바뀐 노트가 남았을 때, 폰이 노트를 받아 가는 중일 때
    return bool(st['done']) or bool(st['pdone']) or len(changed) == 40 or bool(st['want']) or bool(st['rq']) or bool(st['rdone']) or bool(st['iq'])


def save_json(p, data):
    with open(p + '.tmp', 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False)
    os.replace(p + '.tmp', p)


def load_json(p, default):
    try:
        return json.load(open(p, encoding='utf-8'))
    except (OSError, ValueError):
        return default


def sync_loop():
    while True:
        code, more = sync_code(), False
        if code:
            try:
                more = sync_once(code)
                SYNC.update(at=time.time(), err='')
            except Exception as e:
                SYNC['err'] = str(e)[:200]
                print('폰 연동 실패:', e, flush=True)
        if not more:
            SYNC_WAKE.wait(30)                # 30초마다, 맥에서 저장하면 바로
        SYNC_WAKE.clear()
        time.sleep(2)                         # 쓰는 중 저장이 몰려도 2초에 한 번


# ── 읽을 글 (READING 화면): Home 「읽어야 할 글」과 같은 기준 (볼트 90 System/scripts/read-queue.js) ──
# type 이 note·literature 이고 read_on 이 없거나 오늘인 노트. 읽음을 누르면 그 노트의 read_on·memo 두 줄과
# 오늘 데일리 노트의 「오늘 읽은 글」 콜아웃 줄만 고친다. 본문은 맥에서 HTML 로 바꿔 보내고, 색·크기는 볼트의 옵시디언 테마가 정한다

READ_GROUPS = (('work', ('01 Work · 의학물리',)),
               ('clip', ('03 Economy/메르의 블로그', '03 Economy/Valley AI/피드 정리', '03 Economy/Valley AI/시황', '04 Life/읽을거리')),
               ('concept', ('03 Economy/개념', '04 Life/시사 교양')))
READ_HEAD = '> [!abstract]- 오늘 읽은 글'
READ_HEAD_RE = re.compile(r'^>\s?\[!abstract\][+-]?\s*오늘 읽은 글\s*$')
IMG_EXT = ('.png', '.jpg', '.jpeg', '.gif', '.webp', '.svg')


def nfc(s):
    return unicodedata.normalize('NFC', s)


def read_group(folder, f):
    for g, dirs in READ_GROUPS:
        if any(folder == x or folder.startswith(x + '/') for x in dirs):
            return g
    return 'concept' if f.get('origin') == 'question' else None


READ_CACHE = {}                       # 파일 경로 → (mtime, 항목 또는 None). 볼트 노트 1000개를 매번 읽지 않게


def read_item(p, folder, fn, mt):
    fm, body = split(open(p, encoding='utf-8').read())
    if not re.search(r'^type:\s*["\']?(note|literature)["\']?\s*$', fm, re.M):
        return None
    try:
        f = yaml.safe_load(fm) or {}
    except yaml.YAMLError:
        return None
    g = read_group(folder, f)
    if not g:
        return None
    last, ro = re.sub(r'^\d+\s+', '', folder.rsplit('/', 1)[-1]), str(f.get('read_on') or '')[:10]
    return {'rel': f'{folder}/{nfc(fn)}' if folder else nfc(fn), 'title': nfc(fn[:-3]), 'g': g, 'folder': folder,
            'tag': str(f.get('channel') or last) if g == 'clip' else last,
            'desc': str(f.get('description') or ''), 'created': str(f.get('created') or '')[:10],
            'read_on': ro, 'memo': str(f.get('memo') or '') if ro else '',
            'min': max(1, round(len(body) / 500)), 'v': int(mt)}  # 한글 1분에 500자쯤 · v = 노트가 바뀌면 폰이 본문을 다시 받는다


def read_items():
    """읽을 글 목록 (정리일 최근 순). 오늘 읽은 글도 남긴다 (그날 안에는 되돌릴 수 있게)"""
    today_s, out = date.today().isoformat(), []
    for root, dirs, files in os.walk(VAULT):
        dirs[:] = [x for x in dirs if not x.startswith('.')]
        folder = nfc(os.path.relpath(root, VAULT)).replace(os.sep, '/').lstrip('.')
        for fn in files:
            if not fn.endswith('.md'):
                continue
            p = os.path.join(root, fn)
            try:
                mt = os.path.getmtime(p)
                if READ_CACHE.get(p, (None,))[0] != mt:
                    READ_CACHE[p] = (mt, read_item(p, folder, fn, mt))
            except (OSError, UnicodeDecodeError):
                continue
            it = READ_CACHE[p][1]
            if it and (not it['read_on'] or it['read_on'] == today_s):
                out.append(it)
    return sorted(out, key=lambda x: (x['created'], x['title']), reverse=True)


def vault_md(rel):
    """볼트 안에 있는 .md 파일 경로만 (밖으로 나가는 길은 막는다)"""
    rel = nfc(str(rel))
    if not rel.endswith('.md') or rel.startswith(('/', '.')) or '..' in rel.split('/'):
        raise ValueError('잘못된 노트')
    p = os.path.join(VAULT, rel)
    if not os.path.isfile(p) or not os.path.realpath(p).startswith(os.path.realpath(VAULT) + os.sep):
        raise ValueError('노트가 없어요')
    return p


def fm_del(fm, key):
    lines = fm.split('\n')
    i = next((k for k, l in enumerate(lines) if re.match(rf'^{re.escape(key)}:(\s|$)', l)), None)
    if i is None:
        return fm
    j = i + 1
    while j < len(lines) and not TOP.match(lines[j]):
        j += 1
    return '\n'.join(lines[:i] + lines[j:])


def read_lines_set(lines, title, memo):
    """데일리 노트 본문의 「오늘 읽은 글」 콜아웃에서 그 글 줄을 넣거나 고치거나(memo 문자열) 뺀다(memo None).
    콜아웃이 없으면 「오늘 작성·수정한 노트」 바로 아래(없으면 하루 마무리 위)에 만들고, 마지막 줄이 빠지면 콜아웃도 지운다"""
    link = f'> - [[{title}]]'
    h = next((k for k, l in enumerate(lines) if READ_HEAD_RE.match(l)), None)
    if h is None:
        if memo is None:
            return lines
        a = next((k for k, l in enumerate(lines) if l.startswith('>') and '오늘 작성·수정한 노트' in l), None)
        if a is not None:
            e = a + 1
            while e < len(lines) and lines[e].startswith('>'):
                e += 1
            lines, h = lines[:e] + ['', READ_HEAD] + lines[e:], e + 1
        else:
            e = next((k for k, l in enumerate(lines) if l.startswith('>') and '하루 마무리' in l), None)
            if e is None:
                lines, h = lines + ['', READ_HEAD], len(lines) + 1
            else:
                lines, h = lines[:e] + [READ_HEAD, ''] + lines[e:], e
    end = h + 1
    while end < len(lines) and lines[end].startswith('>'):
        end += 1
    items = lines[h + 1:end]
    hit = next((i for i, l in enumerate(items) if l == link or l.startswith(link + ' ')), None)
    if memo is None:
        if hit is not None:
            del items[hit]
    else:
        new = link + (f' - {memo}' if memo else '')
        if hit is None:
            items.append(new)
        else:
            items[hit] = new
    if not items:                                  # 다 빠졌으면 콜아웃과 붙여 넣었던 빈 줄까지 (위, 없으면 아래)
        s = h - 1 if h > 0 and not lines[h - 1].strip() else h
        if s == h and end < len(lines) and not lines[end].strip():
            end += 1
        return lines[:s] + lines[end:]
    return lines[:h + 1] + items + lines[end:]


def read_mark(rel, on, memo, d=None):
    """d = 읽은 날 (폰에서 누른 날. 맥이 늦게 받아도 그날로). 없으면 오늘"""
    p = vault_md(rel)
    memo = ' '.join(str(memo or '').split())[:300]
    d = day(d) if d and real_date(str(d)) and day(d) <= date.today() else date.today()
    with FILE_LOCK:
        fm, body = split(open(p, encoding='utf-8').read())
        if on:
            fm = fm_set(fm, 'read_on', d)
            fm = fm_set(fm, 'memo', memo) if memo else fm_del(fm, 'memo')
        else:                                      # Home 체크를 풀 때처럼 read_on 은 빈 값으로 남긴다
            fm = fm_del(fm_set(fm, 'read_on', None), 'memo')
        write(p, f'---\n{fm}\n---\n{body}')
    if on and not os.path.exists(path(d)):         # 그날 노트가 없으면 데일리 템플릿으로 만든다 (쓰기 시작할 때와 같이)
        created, _ = save_day(d, {}, {})
        if created:
            start_quote(d.isoformat())
    if os.path.exists(path(d)):
        with FILE_LOCK:
            fm, body = split(open(path(d), encoding='utf-8').read())
            lines = read_lines_set(body.split('\n'), nfc(os.path.basename(p))[:-3], memo if on else None)
            write(path(d), f'---\n{fm}\n---\n' + '\n'.join(lines))


# 옵시디언 마크다운 → HTML. 옵시디언에만 있는 문법(콜아웃·[[링크]]·![[그림]]·==형광펜==·%%주석%%)은 앞뒤로 바꿔 끼운다
try:
    from markdown_it import MarkdownIt
    MD = MarkdownIt('commonmark', {'html': False, 'breaks': True}).enable(['table', 'strikethrough'])   # 노트 속 HTML 은 글자로
except ImportError:
    MD = None
CALLOUT = re.compile(r'^>\s?\[!([\w-]+)\]([+-]?)\s*(.*)$')
FENCE = re.compile(r'^\s*(```|~~~)')


def md_inline(s):
    def wiki(m):
        embed, target, alias = m.group(1), m.group(2).strip(), (m.group(3) or '').strip()
        if embed and target.lower().endswith(IMG_EXT):
            return f'![](<img:{target}>)'
        label = (alias if alias and not alias.isdigit() else target.replace('#', ' > ')).replace('[', '\\[').replace(']', '\\]')
        return f'[{label}](<wiki:{target.split("#")[0]}>)'
    s = re.sub(r'(!?)\[\[([^\]|]+)(?:\|([^\]]*))?\]\]', wiki, s)
    return re.sub(r'==(?=\S)(.+?)(?<=\S)==', '\x01\\1\x02', s)


def md_blocks(lines):
    """콜아웃은 따로 떼어 안쪽을 다시 그린다 (콜아웃 안 콜아웃도)"""
    out, buf, fence, i = [], [], False, 0
    flush = lambda: out.append(md_html(MD.render('\n'.join(buf)))) if buf else None
    while i < len(lines):
        l = lines[i]
        if FENCE.match(l):
            fence = not fence
        m = None if fence else CALLOUT.match(l)
        if not m:
            buf.append(l if fence else md_inline(l))
            i += 1
            continue
        flush()
        buf, j = [], i + 1
        while j < len(lines) and lines[j].startswith('>'):
            j += 1
        typ, fold = m.group(1).lower(), m.group(2)
        title = md_html(MD.renderInline(md_inline(m.group(3)))) if m.group(3).strip() else esc_html(typ.capitalize())
        inner = md_blocks([re.sub(r'^>\s?', '', x) for x in lines[i + 1:j]])
        head = f'<div class="callout-icon"></div><div class="callout-title-inner">{title}</div>'
        if fold:
            out.append(f'<details class="callout" data-callout="{esc_html(typ)}"{" open" if fold == "+" else ""}><summary class="callout-title">{head}'
                       f'<div class="callout-fold"></div></summary><div class="callout-content">{inner}</div></details>')
        else:
            out.append(f'<div class="callout" data-callout="{esc_html(typ)}"><div class="callout-title">{head}</div><div class="callout-content">{inner}</div></div>')
        i = j
    flush()
    return ''.join(out)


def esc_html(s):
    return s.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;').replace('"', '&quot;')


def md_html(h):
    from urllib.parse import unquote
    h = re.sub(r'<a href="wiki:([^"]*)">', lambda m: f'<a class="internal-link" data-href="{esc_html(unquote(m.group(1)))}">', h)
    h = re.sub(r'<a href="(https?:[^"]*)">', r'<a class="external-link" href="\1">', h)
    h = re.sub(r'<img src="img:([^"]*)"', lambda m: f'<img src="/api/img?name={quote(unquote(m.group(1)))}"', h)
    h = re.sub(r'<li>(<p>)?\[([ xX])\]\s', lambda m: f'<li class="task-list-item">{m.group(1) or ""}<input type="checkbox" disabled{" checked" if m.group(2) != " " else ""}> ', h)
    h = re.sub(r'<pre><code class="language-dataview(?:js)?">.*?</code></pre>', '<div class="dv-skip">Dataview 목록은 옵시디언에서 보여요</div>', h, flags=re.S)
    return h.replace('\x01', '<mark>').replace('\x02', '</mark>')


def read_doc(rel):
    p = vault_md(rel)
    fm, body = split(open(p, encoding='utf-8').read())
    f = yaml.safe_load(fm) or {}
    if MD is None:
        raise ValueError('이 맥의 파이썬에 markdown-it-py 가 없어요')
    body = re.sub(r'%%.*?%%', '', body, flags=re.S)
    return {'rel': nfc(rel), 'v': int(os.path.getmtime(p)), 'html': md_blocks(body.split('\n')),
            'props': {k: str(f[k])[:10] if k == 'created' else str(f[k]) for k in ('channel', 'description', 'created', 'source') if f.get(k)}}


def attach_path(name):
    """첨부파일 폴더(하위 폴더까지)에서 그림을 이름으로 (옵시디언 ![[이름]] 처럼)"""
    want = nfc(name)
    if '/' in name or not want.lower().endswith(IMG_EXT):
        return None
    return next((os.path.join(r, x) for r, _, fs in os.walk(ATTACH) for x in fs if nfc(x) == want), None)


IMG_W = 1100                                    # 폰에 보내는 그림 폭 (넘으면 줄인다)
IMG_DIR = os.path.join(tempfile.gettempdir(), 'daily-note-img')


def phone_img(name):
    """폰에 보낼 그림 data URL. 맥 sips 로 폭 1100 까지 줄인 JPEG (투명한 PNG 는 PNG 그대로 줄이고, SVG 는 그대로). 줄인 파일은 임시 폴더에 둔다"""
    p = attach_path(name)
    if not p:
        return None
    if p.lower().endswith('.svg'):
        return 'data:image/svg+xml;base64,' + base64.b64encode(open(p, 'rb').read()).decode()
    info = subprocess.run(['sips', '-g', 'pixelWidth', '-g', 'hasAlpha', p], capture_output=True, text=True, timeout=30).stdout
    w = int((re.search(r'pixelWidth: (\d+)', info) or [0, 0])[1])
    fmt = 'png' if re.search(r'hasAlpha: yes', info) else 'jpeg'
    os.makedirs(IMG_DIR, exist_ok=True)
    out = os.path.join(IMG_DIR, hashlib.sha1(f'{p}{os.path.getmtime(p)}'.encode()).hexdigest() + '.' + fmt)
    if not os.path.exists(out):
        subprocess.run(['sips', '-s', 'format', fmt] + (['-s', 'formatOptions', '72'] if fmt == 'jpeg' else [])
                       + (['--resampleWidth', str(IMG_W)] if w > IMG_W else []) + [p, '--out', out], capture_output=True, timeout=60)
    if not os.path.exists(out):
        return None
    return f'data:image/{fmt};base64,' + base64.b64encode(open(out, 'rb').read()).decode()


def theme_css():
    """볼트의 옵시디언 테마를 .ink 안에만 걸리게 (body·:root·.theme-* → .ink, 나머지는 .ink 아래로)"""
    try:
        name = json.load(open(os.path.join(VAULT, '.obsidian', 'appearance.json'), encoding='utf-8')).get('cssTheme') or ''
        css = open(os.path.join(VAULT, '.obsidian', 'themes', name, 'theme.css'), encoding='utf-8').read()
    except (OSError, ValueError):
        return ''
    css, out = re.sub(r'/\*.*?\*/', '', css, flags=re.S), []

    def one(s):
        s = s.strip()
        for head in (':root', 'body'):
            if s.startswith(head):
                return '.ink' + s[len(head):]
        return '.ink' + s if s.startswith(('.theme-', ':is(.theme-')) else '.ink ' + s

    for sel, decl in re.findall(r'([^{}]+)\{([^{}]*)\}', css):
        parts, depth, cur = [], 0, ''
        for ch in sel:                             # :is(a, b) 안의 쉼표는 나누지 않는다
            depth += (ch == '(') - (ch == ')')
            if ch == ',' and depth == 0:
                parts.append(cur)
                cur = ''
            else:
                cur += ch
        out.append(', '.join(one(x) for x in parts + [cur] if x.strip()) + ' {' + decl + '}')
    return '\n'.join(out)


# ── HTTP ──────────────────────────────────────────────────

class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def send(self, code, body, ctype='application/json; charset=utf-8'):
        data = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False, default=str).encode()
        self.send_response(code)
        self.send_header('Content-Type', ctype)
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(data)

    def safe(self):
        # 이 맥 안에서만: 다른 사이트가 localhost 로 요청을 꾸며 보내는 것 막기 (Host 확인 + 앱 표시 헤더)
        host = (self.headers.get('Host') or '').split(':')[0]
        return host in ('127.0.0.1', 'localhost') and (self.command == 'GET' or self.headers.get('X-App') == 'daily-note')

    def do_GET(self):
        if not self.safe():
            return self.send(403, {'error': 'forbidden'})
        u = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        if u.path in ('/', '/index.html'):
            return self.send(200, open(os.path.join(HERE, 'index.html'), 'rb').read(), 'text/html; charset=utf-8')
        if u.path in STATIC:                 # 글칸 편집기(build_cm.sh)·폰 앱 아이콘
            return self.send(200, open(os.path.join(HERE, u.path[1:]), 'rb').read(), STATIC[u.path])
        if u.path == '/api/day':
            if not DATE.match(q.get('date', '')):
                return self.send(400, {'error': '날짜가 이상해요'})
            try:
                n = read_day(day(q['date']))
                n['mind'] = mind_form()
            except (OSError, ValueError, yaml.YAMLError) as e:
                return self.send(500, {'error': str(e)})
            n['today'] = date.today().isoformat()
            if n['date'] == n['today'] and n['quote']['state'] == 'todo' and n['date'] not in TRIED:
                start_quote(n['date'])        # 오늘 명언은 알아서 /명언
            return self.send(200, n)
        if u.path == '/api/days':            # 달력 점: 노트가 있는 날
            return self.send(200, {'dates': note_dates()})
        if u.path == '/api/quotes':          # 명언 모음 화면
            return self.send(200, quote_list())
        if u.path == '/api/plans':           # 일정 카드
            return self.send(200, {'list': plan_list()})
        if u.path == '/api/sync':            # 설정 시트: 폰 연결 코드·마지막으로 맞춘 때
            return self.send(200, dict(SYNC, code=sync_code()))
        if u.path == '/api/job':
            j = dict(JOB)
            if j.get('started'):
                j['elapsed'] = int((j.get('ended') or time.time()) - j['started'])
            return self.send(200, j)
        if u.path == '/api/img':             # 첨부파일 폴더(하위 폴더까지)의 그림을 이름으로 (옵시디언 ![[이름]] 처럼)
            f = attach_path(q.get('name', ''))
            if not f:
                return self.send(404, {'error': 'not found'})
            ext = f.rsplit('.', 1)[-1].lower()
            return self.send(200, open(f, 'rb').read(), 'image/' + {'jpg': 'jpeg', 'svg': 'svg+xml'}.get(ext, ext))
        if u.path == '/api/reads':           # READING 목록
            return self.send(200, {'list': read_items(), 'today': date.today().isoformat()})
        if u.path == '/api/read':            # 노트 본문 (HTML)
            try:
                return self.send(200, read_doc(q.get('rel', '')))
            except (OSError, ValueError, yaml.YAMLError) as e:
                return self.send(404, {'error': str(e)})
        if u.path == '/api/theme.css':       # 볼트의 옵시디언 테마 (.ink 안에만)
            return self.send(200, theme_css().encode(), 'text/css; charset=utf-8')
        self.send(404, {'error': 'not found'})

    def do_POST(self):
        if not self.safe():
            return self.send(403, {'error': 'forbidden'})
        try:
            body = json.loads(self.rfile.read(int(self.headers.get('Content-Length') or 0)) or b'{}')
        except ValueError:
            return self.send(400, {'error': 'bad json'})
        path_, d = urlparse(self.path).path, str(body.get('date', ''))
        if path_ == '/api/plans':            # 일정 체크·추가
            ops = body.get('ops')
            if not isinstance(ops, list) or not all(map(plan_ok, ops)):
                return self.send(400, {'error': '잘못된 요청'})
            try:
                lst = plan_apply(ops)
            except OSError as e:
                return self.send(500, {'error': str(e)})
            SYNC_WAKE.set()
            return self.send(200, {'list': lst})
        if path_ == '/api/readmark':         # 읽음 · 메모 · 되돌리기
            if not isinstance(body.get('on'), bool) or not isinstance(body.get('memo', ''), str):
                return self.send(400, {'error': '잘못된 요청'})
            try:
                read_mark(body.get('rel', ''), body['on'], body.get('memo', ''))
            except (OSError, ValueError) as e:
                return self.send(500, {'error': str(e)})
            SYNC_WAKE.set()
            return self.send(200, {'ok': True, 'today': date.today().isoformat()})
        if path_ == '/api/openurl':          # 노트 속 웹 링크는 기본 브라우저로 (앱 창이 그 사이트로 넘어가지 않게)
            url = str(body.get('url', ''))
            if not re.match(r'^https?://', url):
                return self.send(400, {'error': '잘못된 요청'})
            subprocess.Popen(['open', url])
            return self.send(200, {'ok': True})
        if path_ not in ('/api/open',) and not DATE.match(d):
            return self.send(400, {'error': '날짜가 이상해요'})
        if path_ == '/api/save':
            fmc, secc = body.get('fm') or {}, body.get('sec') or {}
            if not all(ok_fm(k, v) for k, v in fmc.items()) or not all(ok_sec(k, v) for k, v in secc.items()):
                return self.send(400, {'error': '잘못된 요청'})
            try:
                created, mtime = save_day(day(d), fmc, secc)
            except (OSError, ValueError) as e:
                return self.send(500, {'error': str(e)})
            if created:
                start_quote(d)                # 새 노트의 명언은 알아서 /명언
            SYNC_WAKE.set()
            return self.send(200, {'ok': True, 'created': created, 'mtime': mtime})
        if path_ == '/api/fav':              # 별: 📜 명언 모음 노트의 favorites
            if not isinstance(body.get('on'), bool) or not os.path.exists(MOC):
                return self.send(400, {'error': '잘못된 요청'})
            fav_set(d, body['on'])
            SYNC_WAKE.set()
            return self.send(200, {'ok': True})
        if path_ == '/api/quote':
            if not os.path.exists(path(day(d))):
                return self.send(404, {'error': '노트가 없어요'})
            if body.get('again'):
                return self.send(200, {'ok': requote(day(d))})
            if not start_quote(d):
                return self.send(409, {'error': '다른 명언을 정리하는 중이에요'})
            return self.send(200, {'ok': True})
        if path_ == '/api/open':
            rel = str(body.get('rel', ''))            # 볼트 안 경로나 노트 이름 ([[링크]] 처럼 옵시디언이 찾는다)
            if not rel or rel.startswith(('/', '.')) or '..' in rel.split('/') or len(rel) > 300 or re.search(r'[\x00-\x1f]', rel):
                return self.send(400, {'error': '잘못된 요청'})
            subprocess.Popen(['open', f'obsidian://open?vault={quote(os.path.basename(VAULT))}&file={quote(rel)}'])
            return self.send(200, {'ok': True})
        self.send(404, {'error': 'not found'})


if __name__ == '__main__':
    try:
        srv = ThreadingHTTPServer(('127.0.0.1', PORT), H)
    except OSError:
        raise SystemExit('이미 떠 있어요')
    if not os.environ.get('VAULT') or os.environ.get('SYNC_URL'):      # 사본 볼트로 시험할 때는 가짜 연동 서버로만
        threading.Thread(target=sync_loop, daemon=True).start()
    srv.serve_forever()
