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
uv export --project agent-runtime --frozen --no-dev --no-emit-project --format requirements.txt --output-file "$WORK/package/runtime/requirements.lock.txt" >/dev/null
formats=(--only-binary=:all:)
if [ "$TARGET" = darwin-amd64 ]; then
  # Upstream no longer ships Intel wheels; compile on the builder, never on users' Macs.
  command -v rustc >/dev/null || { echo 'Intel macOS builds require Rust' >&2; exit 1; }
  OPENSSL_VERSION=3.5.9
  curl -fSL --retry 3 "https://github.com/openssl/openssl/releases/download/openssl-$OPENSSL_VERSION/openssl-$OPENSSL_VERSION.tar.gz" -o "$WORK/openssl.tar.gz"
  printf '%s  %s\n' 603f5602e2eef00d77fbd429d34dcd5822bb301757a1bc9cdb24c670f1eb859a "$WORK/openssl.tar.gz" | shasum -a 256 -c -
  tar -xzf "$WORK/openssl.tar.gz" -C "$WORK"
  export MACOSX_DEPLOYMENT_TARGET=11.0 OPENSSL_STATIC=1 OPENSSL_DIR="$WORK/openssl"
  (
    cd "$WORK/openssl-$OPENSSL_VERSION"
    ./Configure darwin64-x86_64-cc no-shared no-tests no-module --prefix="$OPENSSL_DIR"
    make -j3
    make install_sw
  ) > "$WORK/openssl-build.log" 2>&1 || { tail -100 "$WORK/openssl-build.log"; exit 1; }
  mkdir -p "$WORK/package/licenses"
  cp "$WORK/openssl-$OPENSSL_VERSION/LICENSE.txt" "$WORK/package/licenses/openssl.txt"
  formats+=(--no-binary=cryptography)
fi
uv run --no-project --python "$PYTHON_EXE" --with pip==25.3 python -m pip wheel --require-hashes --no-cache-dir "${formats[@]}" --wheel-dir "$WORK/package/runtime/wheels" -r "$WORK/package/runtime/requirements.lock.txt"
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
