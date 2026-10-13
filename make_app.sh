#!/bin/zsh
# 데일리 노트.app (main.swift → 맥 앱 한 개, 창 한 개) 를 이 폴더에 만든다. Dock 으로 끌어다 두면 된다.
set -e
cd "$(dirname "$0")"
APP="데일리 노트.app"
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
swiftc -O main.swift -o "$APP/Contents/MacOS/daily-note"
cat > "$APP/Contents/Info.plist" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>CFBundleIdentifier</key><string>com.kimdg0116.daily-note</string>
  <key>CFBundleName</key><string>데일리 노트</string>
  <key>CFBundleDisplayName</key><string>데일리 노트</string>
  <key>CFBundleExecutable</key><string>daily-note</string>
  <key>CFBundleIconFile</key><string>AppIcon</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>1.0</string>
  <key>LSMinimumSystemVersion</key><string>13.0</string>
  <key>NSHighResolutionCapable</key><true/>
  <!-- 서버(127.0.0.1)는 http 라서 이 맥 안 주소만 허용 -->
  <key>NSAppTransportSecurity</key><dict><key>NSAllowsLocalNetworking</key><true/></dict>
  <!-- 번들 ID·설명이 있어야 macOS 가 '데스크톱 폴더 접근 허용' 창을 띄운다 (없으면 조용히 막힘) -->
  <key>NSDesktopFolderUsageDescription</key><string>볼트의 데일리 노트를 읽고 쓰려면 데스크톱 폴더 접근이 필요해요.</string>
</dict></plist>
PLIST
# 아이콘
python3 - <<'PY'
from PIL import Image, ImageDraw
n = 1024
# 주황 그라데이션 바탕 (토플 앱들의 흰 바탕·파란 글자와 겹치지 않게)
bg = Image.new('RGBA', (n, n))
for y in range(n):
    t = y / n
    c = tuple(int(a + (b - a) * t) for a, b in zip((255, 176, 64), (255, 94, 58)))
    ImageDraw.Draw(bg).line((0, y, n, y), fill=c + (255,))
mask = Image.new('L', (n, n), 0)
ImageDraw.Draw(mask).rounded_rectangle((90, 90, n - 90, n - 90), radius=190, fill=255)
im = Image.new('RGBA', (n, n), (0, 0, 0, 0)); im.paste(bg, (0, 0), mask)
d = ImageDraw.Draw(im)
# 노트 한 장: 그림자 + 흰 종이
d.rounded_rectangle((270, 250, 774, 820), radius=48, fill=(180, 60, 20, 90))
d.rounded_rectangle((250, 230, 754, 800), radius=48, fill='white')
# 스프링 고리
for x in (370, 502, 634):
    d.rounded_rectangle((x - 22, 180, x + 22, 290), radius=22, fill='#5a2a14')
# 체크 상자 3줄 (위 둘은 체크, 마지막은 빈 칸)
for i, y in enumerate((380, 510, 640)):
    d.rounded_rectangle((320, y - 34, 388, y + 34), radius=14, outline='#ff6a3a', width=10)
    if i < 2:
        d.line((334, y, 352, y + 20, 378, y - 22), fill='#ff6a3a', width=14, joint='curve')
    d.rounded_rectangle((430, y - 10, 690 - i * 70, y + 10), radius=10, fill='#e6e2dd')
im.save('/tmp/daily-note-icon.png')
PY
rm -rf /tmp/dn.iconset && mkdir /tmp/dn.iconset
for s in 16 32 128 256 512; do
  sips -z $s $s /tmp/daily-note-icon.png --out /tmp/dn.iconset/icon_${s}x${s}.png >/dev/null
  sips -z $((s*2)) $((s*2)) /tmp/daily-note-icon.png --out /tmp/dn.iconset/icon_${s}x${s}@2x.png >/dev/null
done
iconutil -c icns /tmp/dn.iconset -o "$APP/Contents/Resources/AppIcon.icns"
codesign --force --deep -s - "$APP"
touch "$APP"
echo "만듦: $PWD/$APP"
