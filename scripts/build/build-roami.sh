#!/usr/bin/env bash
# 构建「单一自包含」roami 二进制：把前端(frontend/dist)与 ttmux CLI 内嵌进后端。
#
# 用法：
#   scripts/build/build-roami.sh                 # 构建当前平台 → backend/dist/roami-<os>-<arch>
#   GOOS=darwin GOARCH=arm64 scripts/build/build-roami.sh
#   SKIP_FRONTEND=1 GOOS=linux GOARCH=arm64 scripts/build/build-roami.sh   # 复用已构建前端（CI 多目标时）
#
# 结束后会把内嵌占位文件还原，保持工作树干净（避免误提交构建产物）。
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

GOOS="${GOOS:-$(go env GOOS)}"
GOARCH="${GOARCH:-$(go env GOARCH)}"
OUT="${OUT:-backend/dist/roami-$GOOS-$GOARCH}"

WEBUI_DIST="internal/webui/site"

restore() {
  rm -rf "$WEBUI_DIST"; mkdir -p "$WEBUI_DIST"; echo keep > "$WEBUI_DIST/.gitkeep"
}
trap restore EXIT

# 1) 前端构建（架构无关；SKIP_FRONTEND=1 时复用已构建的 frontend/dist）
if [ "${SKIP_FRONTEND:-0}" != "1" ]; then
  ( cd frontend && npm ci && npm run build )
fi
[ -f frontend/dist/index.html ] || { echo "frontend/dist 未构建"; exit 1; }

# 2) 前端产物 → 后端内嵌目录
rm -rf "$WEBUI_DIST"; mkdir -p "$WEBUI_DIST"
cp -r frontend/dist/. "$WEBUI_DIST/"

# 4) 编译 roami（内嵌前端 + CLI；版本号由 ROAMI_BUILD_VERSION 注入，默认 dev）
mkdir -p "$(dirname "$OUT")"
VER="${ROAMI_BUILD_VERSION:-dev}"
CGO_ENABLED=0 GOOS="$GOOS" GOARCH="$GOARCH" \
  go build -ldflags "-X main.version=${VER}" -o "$ROOT/$OUT" ./cmd/roami

echo "built $OUT ($(du -h "$OUT" | cut -f1))"
