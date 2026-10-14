"""python3 test_note.py - 데일리 노트 만들기·칸 읽고 쓰기 확인 (볼트는 템플릿·어제 노트를 읽기만 한다)"""
from datetime import date

import yaml

import server as S

assert S.week_key(date(2026, 10, 13)) == (2026, 42)
assert S.week_key(date(2026, 7, 19)) == (2026, 30)      # 일요일: ISO 주(29)와 다르다
assert S.week_key(date(2026, 12, 29)) == (2027, 1)      # 1월 1일이 든 주는 다음 해 1주

# 템플릿 그대로 만든 노트
d = date(2026, 10, 14)
text = S.render(d, '>[!quote]\n>Be kind.\n>— Someone')
assert '<%' not in text and '[[2026-W42|42주]]' in text and '《 [[2026-10-13(화)]] | [[2026-10-14(수)]] | [[2026-10-15(목)]] 》' in text

# frontmatter: 바꾼 키만, 여러 줄은 |- 블록
fm, body = S.split(text)
for k, v in {'Crossfit_WOD': 'A\n\n  B', 'Crossfit': True, 'mood': 4, 'highlight': 'x: "y" #z', '회고_기록': '잘 됨'}.items():
    fm = S.fm_set(fm, k, v)
fm = S.fm_set(fm, 'mood', None)
y = yaml.safe_load(fm)
assert y['Crossfit_WOD'] == 'A\n\n  B' and y['Crossfit'] is True and y['mood'] is None and y['highlight'] == 'x: "y" #z'
assert y['tags'] == ['daily'] and y['회고_기록'] == '잘 됨' and str(y['date']) == '2026-10-14'
assert 'Crossfit_WOD: |-' in fm

# 본문 칸: 쓰고 다시 읽으면 같다
lines = body.split('\n')
assert S.sec_get(lines, 'study') is None and S.sec_set(lines, 'study', 'x') == lines      # 템플릿에서 공부 칸을 뺐다 (2026-10-14)
for k, v in {'tomorrow': '- [ ] 내일', 'today': '- [x] 오늘 ✅ 2026-10-14\n\t- [ ] 하위',
             'journal': '- 일기\n---\n### 어제 있었던 일\n- 더'}.items():
    lines = S.sec_set(lines, k, v)
    assert S.sec_get(lines, k) == v, k
lines = S.sec_set(lines, 'today', '')
out = '\n'.join(lines)
assert S.sec_get(lines, 'today') == '' and "### Today's Tasks\n없습니다😀\n\n> [!done]- Crossfit" in out
assert "### Tomorrow's Tasks\n- [ ] 내일\n\n### Today's Tasks" in out
old = S.sec_set(['> [!note]+ 공부', '> ', '', '> [!abstract]- x'], 'study', '줄1\n\n줄3')      # 공부 칸이 있는 옛 노트
assert old == ['> [!note]+ 공부', '> 줄1', '>', '> 줄3', '', '> [!abstract]- x'] and S.sec_get(old, 'study') == '줄1\n\n줄3'
assert S.quote_get(lines) == {'text': 'Be kind.', 'author': 'Someone', 'ko': '', 'flag': '', 'link': '', 'toggle': True, 'state': 'todo'}

# /명언 이 정리한 뒤의 모양
done = '''>[!quote]
>We know nothing of tomorrow.
>— Sydney Smith
>
>⚠️ **오용** — 실제는 X (1850). → [[시드니 스미스 (Sydney Smith)]]

> [!info]+ 우리는 내일을 모른다.
> `INPUT[toggle:quote_체크]`
>

⤷ 모아보기 [[📜 명언 모음]] · 저자·출처 [[🗺 명언]] · 이 저자 [[시드니 스미스 (Sydney Smith)]]'''.split('\n')
assert S.quote_get(done) == {'text': 'We know nothing of tomorrow.', 'author': 'Sydney Smith', 'ko': '우리는 내일을 모른다.',
                             'flag': '⚠️ 오용 — 실제는 X (1850). → 시드니 스미스 (Sydney Smith)',
                             'link': '시드니 스미스 (Sydney Smith)', 'toggle': True, 'state': 'done'}
assert S.quote_get(['>[!quote]', '>' + S.FAILED[0], '>— ' + S.FAILED[1]])['state'] == 'failed'

# 예전 노트 (2026-08-08 까지): 명언이 제목 줄에, 번역은 콜아웃 없이 바로 아래 인용 줄에 (또는 빈 [!info] 아래 줄)
old = S.quote_get(['> [!quote] Keep to the **sunshine**.', '> — Helen Keller', '>', '>⚠️ **출처 불명** — x', '',
                   '>**햇살 쪽을 향하라.**', '>**두 번째 줄**', '', '⤷ 모아보기 · 이 저자 [[헬렌 켈러 (Helen Keller)]]'])
assert (old['text'], old['ko'], old['toggle'], old['state']) == ('Keep to the sunshine.', '햇살 쪽을 향하라.', False, 'done'), old
assert S.quote_get(['> [!quote] A.', '> — B', '', '>[!info]  ', '>"존재한다는 것"', ''])['ko'] == '존재한다는 것'
assert S.quote_get(['>[!quote]', '>A.', '>— B', '', '> [!info]+ "English again."', '> 한글 번역', '> `INPUT[toggle:quote_체크]`'])['ko'] == '한글 번역'

# 별: 📜 명언 모음 노트의 favorites 만 고친다 (옵시디언 모양 그대로)
import os, tempfile
S.MOC = os.path.join(tempfile.mkdtemp(), 'moc.md')
open(S.MOC, 'w').write('---\ntitle: 명언 모음\nfavorites:\n  - "[[2026-08-16(일)]]"\n  - "[[2026-09-22(화)]]"\ntags:\n  - quote\n---\n# 본문\n')
S.fav_set('2026-10-13', True); S.fav_set('2026-08-16', False); S.fav_set('2026-10-13', True)
assert open(S.MOC).read() == '---\ntitle: 명언 모음\nfavorites:\n  - "[[2026-09-22(화)]]"\n  - "[[2026-10-13(화)]]"\ntags:\n  - quote\n---\n# 본문\n'
S.fav_set('2026-09-22', False); S.fav_set('2026-10-13', False)
assert 'favorites: []\ntags:' in open(S.MOC).read() and S.fav_get(S.split(open(S.MOC).read())[0]) == []
S.fav_set('2026-10-13', True)
assert S.fav_get(S.split(open(S.MOC).read())[0]) == ['2026-10-13']

# 마음 기록 양식은 템플릿에서 읽는다
mind = S.mind_form()
names = [m['name'] for m in mind if 'name' in m]
assert names[:2] == ['회고', '음미하기'] and mind[2] == {'sep': True} and names[-1] == '강점체크', names
cog = next(m for m in mind if m.get('name') == '인지재구성')
assert cog['check'] == '인지재구성_체크' and cog['items'][0]['ask'][0]['text'].startswith('오늘 그 생각에')
assert [i['toggle'] for i in cog['items'] if 'toggle' in i][:2] == ['인지왜곡_파국화', '인지왜곡_흑백사고']
kind = next(m for m in mind if m.get('name') == '자기자비')
assert [a['label'] for a in kind['items'][0]['ask']] == ['self-kindness', 'common humanity', 'mindfulness']
# 폰에서 고친 칸 고르기: 맥이 안 고쳤으면 폰 것, 둘 다 고쳤으면 나중 것, 이상한 키는 버리되 받았다고는 알린다
cur = {'fm': {'mood': 3, 'highlight': 'a'}, 'sec': {'journal': 'x', 'today': ''}}
o = {'fm': {'mood': {'v': 4, 't': 1000, 'b': 3}, 'highlight': {'v': 'phone', 't': 1000, 'b': 'old'}, 'date': {'v': 'x', 't': 1, 'b': ''}},
     'sec': {'journal': {'v': 'y', 't': 5000, 'b': 'z'}, 'today': {'v': '', 't': 9, 'b': None}, 'bogus': {'v': 'q', 't': 1, 'b': ''}}}
fmc, secc, done = S.pick(cur, 3000, o)
assert fmc == {'mood': 4} and secc == {'journal': 'y'} and len(done) == 6, (fmc, secc, done)
assert S.sec_set(['### <font>Journal</font>', '- a', '', '#### #회고'], 'journal', '') == ['### <font>Journal</font>', '', '#### #회고']
print('ok')
