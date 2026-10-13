#!/bin/zsh
# cm.js = 글칸 편집기(CodeMirror 6) 묶음. 평소엔 만들 필요 없다 (cm.js 를 그대로 쓴다). 버전을 올릴 때만 다시 돌린다.
set -e
cd "$(dirname "$0")"
T=$(mktemp -d)
trap 'rm -rf $T' EXIT
cat > $T/entry.js <<'JS'
export { EditorState } from '@codemirror/state';
export { EditorView, keymap, placeholder, Decoration, ViewPlugin, WidgetType } from '@codemirror/view';
export { history, historyKeymap, defaultKeymap } from '@codemirror/commands';
JS
cd $T
npm init -y >/dev/null
npm i --silent --no-audit --no-fund @codemirror/state@6 @codemirror/view@6 @codemirror/commands@6 esbuild@0
npx esbuild entry.js --bundle --format=esm --minify --legal-comments=none --outfile=cm.js
V=$(node -p "['state','view','commands'].map(p => p + ' ' + JSON.parse(require('fs').readFileSync('node_modules/@codemirror/' + p + '/package.json')).version).join(', ')")
cd - >/dev/null
{ echo "/* CodeMirror 6 ($V), MIT. build_cm.sh 로 만듦 */"; cat $T/cm.js; } > cm.js
echo "만듦: cm.js ($V)"
