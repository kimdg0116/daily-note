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
from PIL import Image, ImageDraw, ImageFont
F = '/System/Library/Fonts/Avenir Next Condensed.ttc'
n = 1024
im = Image.new('RGBA', (n, n), (0, 0, 0, 0)); d = ImageDraw.Draw(im)
d.rounded_rectangle((90, 90, n - 90, n - 90), radius=190, fill='white')
d.text((n/2, n*0.36), 'DAILY', font=ImageFont.truetype(F, 210, index=0), fill='#2e70ff', anchor='mm')
d.text((n/2, n*0.56), 'NOTE', font=ImageFont.truetype(F, 150, index=0), fill='#1428a0', anchor='mm')
d.rounded_rectangle((n*0.32, n*0.70, n*0.68, n*0.72), radius=8, fill='#2e70ff')
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
