#!/usr/bin/env bash
# Complete native release: no Python or package-index access needed on the target.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
OS="$(go env GOOS)"; ARCH="$(go env GOARCH)"
TARGET="$OS-$ARCH"
VERSION="${ROAMI_BUILD_VERSION:-dev}"
PYTHON_VERSION=3.12.13
ASSET="roami-$TARGET"
BINARY="${ROAMI_BUNDLE_BINARY:-$ROOT/backend/dist/$ASSET}"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
mkdir -p "$WORK/package/bin" "$WORK/package/runtime/wheels" "$ROOT/backend/dist"
cp "$BINARY" "$WORK/package/bin/roami"
PYTHON_STORE="${UV_PYTHON_INSTALL_DIR:-${XDG_CACHE_HOME:-$HOME/.cache}/roami-build/python}"
uv python install "$PYTHON_VERSION" --install-dir "$PYTHON_STORE" --no-bin
PYTHON_EXE="$(UV_PYTHON_INSTALL_DIR="$PYTHON_STORE" uv python find --managed-python --no-python-downloads "$PYTHON_VERSION")"
uv build --wheel --out-dir "$WORK/package/runtime/wheels" agent-runtime
uv export --project agent-runtime --frozen --no-dev --no-emit-project --format requirements.txt --output-file "$WORK/package/runtime/requirements.txt" >/dev/null
uv run --no-project --python "$PYTHON_EXE" --with pip==25.3 python -m pip download --require-hashes --only-binary=:all: --dest "$WORK/package/runtime/wheels" -r "$WORK/package/runtime/requirements.txt"
mkdir -p "$WORK/package/install"
cp scripts/install/retire-session-entries.sh "$WORK/package/install/"
cp agent-runtime/pyproject.toml "$WORK/package/runtime/pyproject.toml"
uv run --no-project --python "$PYTHON_EXE" python scripts/build/agent-bundle-manifest.py "$WORK/package" "$PYTHON_EXE" "$VERSION" "$TARGET" "$(git rev-parse HEAD)"
tar -czf "$ROOT/backend/dist/$ASSET.tar.gz" -C "$WORK/package" bin runtime install licenses manifest.json
if command -v sha256sum >/dev/null; then
 (cd backend/dist && sha256sum "$ASSET.tar.gz" > "$ASSET.tar.gz.sha256")
else
 (cd backend/dist && shasum -a 256 "$ASSET.tar.gz" > "$ASSET.tar.gz.sha256")
fi
echo "built backend/dist/$ASSET.tar.gz"
