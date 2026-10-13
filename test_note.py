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
for k, v in {'tomorrow': '- [ ] 내일', 'today': '- [x] 오늘 ✅ 2026-10-14\n\t- [ ] 하위', 'study': '줄1\n\n줄3',
             'journal': '- 일기\n---\n### 어제 있었던 일\n- 더'}.items():
    lines = S.sec_set(lines, k, v)
    assert S.sec_get(lines, k) == v, k
lines = S.sec_set(lines, 'today', '')
out = '\n'.join(lines)
assert S.sec_get(lines, 'today') == '' and "### Today's Tasks\n없습니다😀\n\n> [!done]- Crossfit" in out
assert "### Tomorrow's Tasks\n- [ ] 내일\n\n### Today's Tasks" in out and '> [!note]+ 공부\n> 줄1\n>\n> 줄3\n\n> [!abstract]' in out
assert S.quote_get(lines) == {'text': 'Be kind.', 'author': 'Someone', 'ko': '', 'flag': '', 'link': '', 'state': 'todo'}

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
                             'link': '시드니 스미스 (Sydney Smith)', 'state': 'done'}
assert S.quote_get(['>[!quote]', '>' + S.FAILED[0], '>— ' + S.FAILED[1]])['state'] == 'failed'

# 마음 기록 양식은 템플릿에서 읽는다
mind = S.mind_form()
names = [m['name'] for m in mind if 'name' in m]
assert names[:2] == ['회고', '음미하기'] and mind[2] == {'sep': True} and names[-1] == '강점체크', names
cog = next(m for m in mind if m.get('name') == '인지재구성')
assert cog['check'] == '인지재구성_체크' and cog['items'][0]['ask'][0]['text'].startswith('오늘 그 생각에')
assert [i['toggle'] for i in cog['items'] if 'toggle' in i][:2] == ['인지왜곡_파국화', '인지왜곡_흑백사고']
kind = next(m for m in mind if m.get('name') == '자기자비')
assert [a['label'] for a in kind['items'][0]['ask']] == ['self-kindness', 'common humanity', 'mindfulness']
print('ok')
