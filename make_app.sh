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
# 크림 수첩 + 해돋이 바탕(보라 → 주황). 2배로 그려 줄여서 가장자리 매끈하게. 폰 앱 아이콘(꽉 찬 사각)도 같이 만든다
from PIL import Image, ImageDraw
S = 2048
def hexc(h): return tuple(int(h[i:i+2], 16) for i in (1, 3, 5))
im = Image.new('RGBA', (S, S)); d = ImageDraw.Draw(im)
for y in range(S):
    t = y / S; d.line((0, y, S, y), fill=tuple(int(a + (b - a) * t) for a, b in zip(hexc('#3b2a7a'), hexc('#ff8a5c'))))
x0, y0, x1, y1 = S*0.27, S*0.18, S*0.73, S*0.82
sh = Image.new('RGBA', (S, S), (0, 0, 0, 0))
ImageDraw.Draw(sh).rounded_rectangle((x0 + 30, y0 + 40, x1 + 30, y1 + 40), radius=80, fill=(30, 10, 40, 90))
im.alpha_composite(sh); d = ImageDraw.Draw(im)
d.rounded_rectangle((x0, y0, x1, y1), radius=80, fill='#fff3e0')         # 표지
d.rectangle((x0, y0, x0 + 70, y1), fill='#f2dcc0')                         # 책등
d.rectangle((x1 - 150, y0, x1 - 110, y1), fill='#e0c3a0')                  # 고무줄
rx = S*0.48                                                                 # 책갈피 끈
d.polygon([(rx - 50, y1 - 20), (rx + 50, y1 - 20), (rx + 50, y1 + 190), (rx, y1 + 140), (rx - 50, y1 + 190)], fill='#ff8a5c')
d.rounded_rectangle((S*0.40, S*0.32, S*0.60, S*0.40), radius=20, fill='#ff8a5c')  # 이름표
full = im.convert('RGB')
for name, n in (('icon-512.png', 512), ('icon-192.png', 192), ('apple-touch-icon.png', 180)):
    full.resize((n, n), Image.LANCZOS).save(name)
m = Image.new('L', (S, S), 0); ImageDraw.Draw(m).rounded_rectangle((180, 180, S - 180, S - 180), radius=380, fill=255)
mac = Image.new('RGBA', (S, S), (0, 0, 0, 0)); mac.paste(full, (0, 0), m)
mac.resize((1024, 1024), Image.LANCZOS).save('/tmp/daily-note-icon.png')
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
