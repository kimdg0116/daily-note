# 데일리 노트 (맥 앱 + 폰 앱)

옵시디언 데일리 노트(`04 Life/Planner/Daily/YYYY-MM-DD(요일).md`)를 앱 화면으로 쓴다. 쓰는 대로(0.5초 뒤) 그 노트에 저장되고, 옵시디언에서 고쳐도 같은 노트다.

- 실행: `데일리 노트.app` 더블클릭 (Dock 에 끌어다 두기). 한 번만 뜨고 Dock 을 다시 누르면 있던 창이 앞으로 온다. 서버가 없으면 앱이 띄운다.
  - 앱만 데스크톱 등으로 옮겨 둬도 된다 (서버는 이 폴더 것을 쓴다). 앱이 없거나 `main.swift` 를 고쳤으면 `./make_app.sh`.
  - `server.py` 를 고쳤으면 서버를 다시 켜야 한다 (명언 정리 중이 아닐 때 서버를 끄고 앱에서 ⌘R - 서버가 없으면 앱이 다시 띄운다). 서버만은 `python3 server.py` (127.0.0.1:8749, 로그 `/tmp/daily-note.log`).
- 날짜를 고르면 그 날 노트를 연다. 노트가 없는 날은 쓰기 시작할 때 데일리 템플릿 그대로 만든다 (Templater 대신 앱이 날짜 링크, 어제 Tomorrow's Tasks, 오늘의 명언을 채운다).
- 칸 대부분이 frontmatter 값(meta-bind)이라 바꾼 키만 고친다. 할 일·공부·Journal 은 본문 그 자리만 고친다.
- 날짜 버튼을 누르면 달력이 뜨고, 노트가 있는 날에 점이 찍힌다.
- 운동 기록·Journal·마음 기록 칸은 편집기(CodeMirror, `cm.js`)라 옵시디언처럼 `**굵게**`(⌘B)의 기호는 숨기고(커서가 그 안에 오면 보임) 줄 맨 앞 `- ` 는 점으로 보여 준다. 노트에는 마크다운 그대로 저장된다. `cm.js` 는 `build_cm.sh` 로 만든 묶음이라 평소엔 손대지 않는다.
- 마음 기록(#회고 ~ #강점체크) 칸은 템플릿을 읽어서 만든다 (템플릿의 `---` 로 나뉜 묶음마다 카드 하나). 템플릿에 질문을 더하면 앱에도 생긴다. 템플릿 위쪽(할 일·운동·하루 마무리)이나 Templater 코드를 바꾸면 `server.py` 도 같이 본다 (모르는 Templater 코드가 있으면 노트를 만들지 않고 알린다).
- 명언: 새 노트를 만들 때, 그리고 오늘 노트에 정리 안 된 명언이 있으면 `claude -p "/명언 <날짜>"` 를 알아서 돌린다. 끝나면 번역·판정·저자 카드가 뜨고, 저자 노트는 옵시디언 `04 Life/명언/저자/` 에 있다.

## 폰 앱 · 연동
- 폰 앱 = 같은 `index.html` 을 GitHub Pages(`kimdg0116/daily-note`)로 띄운 홈 화면 앱. https 로 열리면 폰 모드가 된다 (manifest·sw.js·version.json, 앱 버전은 `APP_VERSION`·`sw.js`·`version.json` 세 곳 같이).
- 연동은 토플 단어 앱처럼 Apps Script 우체통(`sync/Code.js`, 프로젝트 "데일리 노트 동기화"). 맥 `server.py` 가 30초마다(맥에서 저장하면 바로) 최근 노트(35일 전 ~ 7일 뒤)를 올리고, 폰에서 고친 칸을 받아 볼트에 쓴다. 맥이 꺼져 있으면 폰 수정은 우체통에 남았다가 맥 서버가 켜질 때 들어간다.
- 같은 칸을 폰과 맥에서 둘 다 고쳤으면 나중에 고친 쪽이 이긴다 (`server.py` `pick`).
- 연결 코드는 `sync/Secret.js` (git 제외). 맥 앱 설정 > 폰 연동에 보이고, 폰 앱 설정에 넣는다.
- 연동 서버 반영: `cd sync && ~/Desktop/app/dosimetrist-calendar-server/tools/node_modules/.bin/clasp push -f && …/clasp redeploy AKfycbwAzbhrtPtjrd8KVQuFTFXfgLmzY4Cgsk-DZlF2ur3b6a7hU_LMQOaKddSt-0O9mOIP -d "설명"`
- 맥에서 폰 화면 시험: `node sync/test_sync.mjs --serve`(가짜 우체통 8751) + `http://127.0.0.1:8749/?phone`. localhost 의 폰 모드는 늘 가짜 우체통으로만 간다 (진짜 노트에 시험 글이 섞이지 않게).

확인: `python3 test_note.py` (템플릿 렌더·칸 읽고 쓰기·명언 칸·마음 기록 양식·폰 수정 고르기), `node sync/test_sync.mjs` (우체통)
시험: `VAULT=<사본 볼트> CLAUDE=<가짜 claude> [SYNC_URL=http://127.0.0.1:8751] python3 server.py` 로 실제 볼트를 건드리지 않고 돌려 볼 수 있다.
