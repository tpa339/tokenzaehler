#!/bin/sh
# Baut Tokenzaehler.app (Menüleisten-App) neben diesem Skript.
set -e
cd "$(dirname "$0")"
APP=Tokenzaehler.app
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS"
swiftc -O -parse-as-library -o "$APP/Contents/MacOS/Tokenzaehler" Tokenzaehler.swift
cat > "$APP/Contents/Info.plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>CFBundleExecutable</key><string>Tokenzaehler</string>
<key>CFBundleIdentifier</key><string>local.tokenzaehler</string>
<key>CFBundleName</key><string>Tokenzähler</string>
<key>CFBundlePackageType</key><string>APPL</string>
<key>LSUIElement</key><true/>
<key>TZSkript</key><string>$(cd .. && pwd)/tokenzaehler.py</string>
</dict></plist>
EOF
codesign -s - --force "$APP" >/dev/null 2>&1 || true
echo "Gebaut: $(pwd)/$APP"
