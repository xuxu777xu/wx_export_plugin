#!/bin/zsh
# 编译、组装、本机签名、安装到 ~/Applications 并向系统注册分享扩展。全过程写 build/build.log。
set -euo pipefail

root=${0:A:h}
build="$root/build"
mkdir -p "$build"
log="$build/build.log"
exec > >(tee -a "$log") 2>&1

version=$(<"$root/VERSION")
echo "[$(date '+%F %T')] 构建 WxToOb $version"

app="$build/WxToOb.app"
appex="$app/Contents/PlugIns/WxShare.appex"
rm -rf "$app"
mkdir -p "$app/Contents/MacOS" "$app/Contents/Resources" "$appex/Contents/MacOS"
cp "$root/Resources/AppIcon.icns" "$root/Resources/process.sh" "$app/Contents/Resources/"

echo "→ 编译宿主 App"
swiftc -O -target arm64-apple-macos14.0 \
  -o "$app/Contents/MacOS/WxToOb" "$root/Sources/App/main.swift"

echo "→ 编译分享扩展"
# 扩展没有 main，入口由系统的 NSExtensionMain 提供。
swiftc -O -target arm64-apple-macos14.0 -parse-as-library -application-extension \
  -module-name WxShare \
  -Xlinker -e -Xlinker _NSExtensionMain \
  -o "$appex/Contents/MacOS/WxShare" "$root"/Sources/Share/*.swift

sed "s/__VERSION__/$version/g" "$root/Resources/App-Info.plist" > "$app/Contents/Info.plist"
sed "s/__VERSION__/$version/g" "$root/Resources/Share-Info.plist" > "$appex/Contents/Info.plist"
plutil -lint "$app/Contents/Info.plist" "$appex/Contents/Info.plist"

echo "→ 本机签名（先扩展后 App）"
codesign --force --sign - --entitlements "$root/Resources/Share.entitlements" "$appex"
codesign --force --sign - "$app"
codesign --verify --strict --verbose=2 "$app"

dest="$HOME/Applications/WxToOb.app"
echo "→ 安装到 $dest"
mkdir -p "$HOME/Applications"
if [ -d "$dest" ]; then
  pluginkit -r "$dest/Contents/PlugIns/WxShare.appex"
  rm -rf "$dest"
fi
cp -R "$app" "$dest"

echo "→ 注册"
lsregister=/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister
"$lsregister" -f -R "$dest"
pluginkit -a "$dest/Contents/PlugIns/WxShare.appex"
pluginkit -e use -i com.xuxu.wxtoob.share

echo "→ 注册结果"
pluginkit -mAvvv -i com.xuxu.wxtoob.share

echo "→ 安装后台任务 com.xuxu.wxtoob.process"
mkdir -p "$HOME/Library/Application Support/WxToOb/queue"
agent="$HOME/Library/LaunchAgents/com.xuxu.wxtoob.process.plist"
domain="gui/$(id -u)"
if launchctl print "$domain/com.xuxu.wxtoob.process" >/dev/null 2>&1; then
  launchctl bootout "$domain/com.xuxu.wxtoob.process"
fi
sed "s#__HOME__#$HOME#g" "$root/Resources/process.plist" > "$agent"
plutil -lint "$agent"
launchctl bootstrap "$domain" "$agent"
launchctl print "$domain/com.xuxu.wxtoob.process" | grep -E "state|path ="
echo "[$(date '+%F %T')] 完成"
