#!/usr/bin/env bash
# 构建 Roami Android App（mobile/android），支持本地安装和 Release 产物。
#
# 用法：scripts/build/build-apk.sh [--install | --publish DIR]
#   产物 mobile/android/app/build/outputs/apk/release/app-release.apk
#   --install 把它放到 ~/.roami/roami.apk，Roami 在 /api/apk 下发，手机上「装到手机」页就有下载按钮（不用重启）
#   --publish DIR 要求固定签名证书，输出 roami.apk、校验文件与实际 App 版本
#
# 依赖：JDK 17+、Android SDK。首次会下载 Gradle 与依赖。
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
MODE="${1:-}"
case "$MODE" in
  '') [ "$#" -eq 0 ] ;;
  --install) [ "$#" -eq 1 ] ;;
  --publish) [ "$#" -eq 2 ] && [ -n "$2" ] ;;
  *) echo 'Usage: build-apk.sh [--install | --publish DIR]' >&2; exit 2 ;;
esac
if [ -n "${ROAMI_ANDROID_KEYSTORE:-}" ]; then
  [ -f "$ROAMI_ANDROID_KEYSTORE" ] || { echo 'Release keystore not found' >&2; exit 1; }
  ROAMI_ANDROID_KEYSTORE="$(cd "$(dirname "$ROAMI_ANDROID_KEYSTORE")" && pwd)/$(basename "$ROAMI_ANDROID_KEYSTORE")"
  export ROAMI_ANDROID_KEYSTORE
fi
OUTPUT=""
if [ "$MODE" = --publish ]; then
  for name in ROAMI_ANDROID_KEYSTORE ROAMI_ANDROID_STORE_PASSWORD ROAMI_ANDROID_KEY_ALIAS ROAMI_ANDROID_KEY_PASSWORD; do
    [ -n "${!name:-}" ] || { echo "Missing release signing setting: $name" >&2; exit 1; }
  done
  mkdir -p "$2"
  OUTPUT="$(cd "$2" && pwd)"
fi
if [ -z "${ANDROID_HOME:-}" ]; then
  for sdk in "${ANDROID_SDK_ROOT:-}" "$HOME/android-sdk" "$HOME/Android/Sdk" "$HOME/Library/Android/sdk"; do
    if [ -n "$sdk" ] && [ -d "$sdk" ]; then ANDROID_HOME="$sdk"; break; fi
  done
fi
export ANDROID_HOME="${ANDROID_HOME:-}"
# 两个变量指向不同目录时 Gradle 直接拒绝构建；ANDROID_SDK_ROOT 已弃用，统一成一个
export ANDROID_SDK_ROOT="$ANDROID_HOME"
[ -d "$ANDROID_HOME" ] || { echo "缺 Android SDK：装 cmdline-tools 后 sdkmanager \"platforms;android-35\" \"build-tools;35.0.0\"，或设 ANDROID_HOME" >&2; exit 1; }
cd "$ROOT/mobile/android"
./gradlew --no-daemon -q assembleRelease
APK=app/build/outputs/apk/release/app-release.apk
echo "✔ $APK ($(du -h "$APK" | cut -f1))"
if [ "$MODE" = --install ] || [ "$MODE" = --publish ]; then
  TOOLS="$ANDROID_HOME/build-tools/35.0.0"
  VERSION="$("$TOOLS/aapt" dump badging "$APK" | sed -n "s/^package:.*versionName='\([^']*\)'.*/\1/p")"
  [ -n "$VERSION" ] || { echo 'APK version is missing' >&2; exit 1; }
fi
if [ "$MODE" = --install ]; then
  DATA="${ROAMI_DATA_DIR:-$HOME/.roami}"
  mkdir -p "$DATA"
  cp "$APK" "$DATA/roami.apk"
  # 版本号记在旁边：服务端据此告诉 App「有新版」，不用每次都让人去猜装的是哪一版
  printf '%s\n' "$VERSION" > "$DATA/roami.apk.version"
  echo "✔ 已放到 $DATA/roami.apk，手机上 我 › 装到手机 › 下载 apk"
fi
if [ "$MODE" = --publish ]; then
  "$TOOLS/apksigner" verify --verbose --print-certs "$APK"
  cp "$APK" "$OUTPUT/roami.apk"
  printf '%s\n' "$VERSION" > "$OUTPUT/roami.apk.version"
  (cd "$OUTPUT"; if command -v sha256sum >/dev/null; then sha256sum roami.apk; else shasum -a 256 roami.apk; fi) > "$OUTPUT/roami.apk.sha256"
  echo "Published APK artifacts: $OUTPUT (Android $VERSION)"
fi
