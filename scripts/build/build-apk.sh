#!/usr/bin/env bash
# 打 Roami 的 Android App（mobile/android）。Roami 是自托管的，没有商店里的包：部署者自己打、自己装。
#
# 用法：scripts/build/build-apk.sh [--install]
#   产物 mobile/android/app/build/outputs/apk/release/app-release.apk
#   --install 把它放到 ~/.roami/roami.apk，Roami 在 /api/apk 下发，手机上「装到手机」页就有下载按钮（不用重启）
#
# 依赖：JDK 17、Android SDK（ANDROID_HOME，或 ~/android-sdk）。首次会下 Gradle 与依赖。
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
export ANDROID_HOME="${ANDROID_HOME:-$HOME/android-sdk}"
# 两个变量指向不同目录时 Gradle 直接拒绝构建；ANDROID_SDK_ROOT 已弃用，统一成一个
export ANDROID_SDK_ROOT="$ANDROID_HOME"
[ -d "$ANDROID_HOME" ] || { echo "缺 Android SDK：装 cmdline-tools 后 sdkmanager \"platforms;android-36\" \"build-tools;35.0.0\"，或设 ANDROID_HOME" >&2; exit 1; }
cd "$ROOT/mobile/android"
./gradlew --no-daemon -q assembleRelease
APK=app/build/outputs/apk/release/app-release.apk
echo "✔ $APK ($(du -h "$APK" | cut -f1))"
if [ "${1:-}" = "--install" ]; then
  DATA="${ROAMI_DATA_DIR:-$HOME/.roami}"
  cp "$APK" "$DATA/roami.apk"
  # 版本号记在旁边：服务端据此告诉 App「有新版」，不用每次都让人去猜装的是哪一版
  sed -n 's/.*versionName = "\([^"]*\)".*/\1/p' app/build.gradle.kts | head -1 > "$DATA/roami.apk.version"
  echo "✔ 已放到 $DATA/roami.apk，手机上 我 › 装到手机 › 下载 apk"
fi
