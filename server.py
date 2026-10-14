"""데일리 노트 - 맥에서만 도는 작은 서버.

볼트의 데일리 노트(04 Life/Planner/Daily/YYYY-MM-DD(요일).md)를 앱 화면으로 쓰고 고친다.
- 칸은 거의 다 frontmatter 값이라(meta-bind) 그 키만 바꾸고, 할 일·공부·Journal 은 본문 그 자리만 바꾼다
- 노트가 없는 날은 쓰기 시작할 때 데일리 템플릿 그대로 만든다 (Templater 가 하던 일: 날짜 링크, 어제 Tomorrow's Tasks, 오늘의 명언)
- 새 명언은 Claude Code 를 `claude -p "/명언 <날짜>"` 로 불러 번역·저자 노트까지 정리한다

    python3 server.py          서버만 (127.0.0.1:8749). 폰 연동(sync/Secret.js 가 있으면)도 같이 돈다
    VAULT=<사본 볼트> CLAUDE=<가짜 claude> [SYNC_URL=<가짜 연동 서버>] python3 server.py    시험용 (사본 볼트면 진짜 연동 서버로는 안 보낸다)
"""
import hashlib, json, os, re, shutil, subprocess, threading, time, unicodedata, urllib.request
from datetime import date, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs, quote

import yaml

PORT = 8749
HERE = os.path.dirname(os.path.abspath(__file__))
VAULT = os.environ.get('VAULT') or os.path.expanduser('~/Desktop/Obsidian_Dongkyu')
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

MOC = os.path.join(VAULT, '04 Life', '📜 명언 모음.md')
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


def mind_form():
    """템플릿의 Journal 아래 마음 기록 칸들을 그대로 읽어 화면 양식으로 (템플릿을 고치면 앱도 따라간다)"""
    lines = open(TEMPLATE, encoding='utf-8').read().split('\n')
    start = next((i for i, l in enumerate(lines) if l.startswith('### ') and 'Journal' in l), len(lines))
    out, cur, ask = [], None, []
    for l in lines[start + 1:]:
        if 'randomQuote' in l:
            break
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
    return out


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
    return {'date': d.isoformat(), 'name': fname(d), 'exists': exists, 'week': wk,
            'mtime': os.path.getmtime(p) if exists else 0,
            'fm': yaml.safe_load(fm) or {}, 'sec': {k: sec_get(lines, k) for k in SECS},
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
    mind, quotes = mind_form(), quote_list()
    dh, mh, qh = (hashlib.sha1(json.dumps(x, ensure_ascii=False).encode()).hexdigest() for x in (dates, mind, quotes))
    if st.get('fmt') != 2:                # 노트 읽는 법이 바뀌었다(예전 명언 형식) → 폰 사본도 한 번 다시 보낸다
        st.update(up={d: 0 for d in mt} if 'up' in st else dict(mt), fmt=2)
    up = st.setdefault('up', dict(mt))    # 처음엔 지금 상태를 기준으로만 (노트 내용은 폰이 '다시 받기'로 가져간다)
    changed = [d for d in dates if up.get(d) != mt[d]][:40]           # 맥에서 바뀐 노트 (한 번에 40개까지)
    put = {d: phone_doc(day(d)) for d in changed}
    body = {'code': code, 'op': 'mac', 'done': st.get('done', []), 'put': put}
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
    r = sync_post(body)
    if r.get('err'):
        raise RuntimeError('연결 코드가 맞지 않아요' if r['err'] == 'code' else r['err'])
    up.update({d: mt[d] for d in put})
    st.update(done=[], dh=dh, mh=mh, qh=qh, want=r.get('want'))
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
    return bool(st['done']) or len(changed) == 40 or bool(st['want'])


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
        if u.path == '/api/sync':            # 설정 시트: 폰 연결 코드·마지막으로 맞춘 때
            return self.send(200, dict(SYNC, code=sync_code()))
        if u.path == '/api/job':
            j = dict(JOB)
            if j.get('started'):
                j['elapsed'] = int((j.get('ended') or time.time()) - j['started'])
            return self.send(200, j)
        if u.path == '/api/img':
            name = q.get('name', '')
            want = unicodedata.normalize('NFC', name)
            f = next((f for f in (os.listdir(ATTACH) if os.path.isdir(ATTACH) and '/' not in name else [])
                      if unicodedata.normalize('NFC', f) == want), None)
            if not f:
                return self.send(404, {'error': 'not found'})
            ext = f.rsplit('.', 1)[-1].lower()
            return self.send(200, open(os.path.join(ATTACH, f), 'rb').read(), 'image/' + ('jpeg' if ext == 'jpg' else ext))
        self.send(404, {'error': 'not found'})

    def do_POST(self):
        if not self.safe():
            return self.send(403, {'error': 'forbidden'})
        try:
            body = json.loads(self.rfile.read(int(self.headers.get('Content-Length') or 0)) or b'{}')
        except ValueError:
            return self.send(400, {'error': 'bad json'})
        path_, d = urlparse(self.path).path, str(body.get('date', ''))
        if path_ != '/api/open' and not DATE.match(d):
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
            rel = str(body.get('rel', ''))
            if not rel.startswith('04 Life/') or '..' in rel:
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
