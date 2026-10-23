#!/usr/bin/env bash
set -euo pipefail
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
SANDBOX="$(mktemp -d /tmp/roami-release-discovery.XXXXXX)"
trap 'rm -rf "$SANDBOX"' EXIT
sed '/^# ── 主流程/,$d' "$REPO_DIR/install.sh" > "$SANDBOX/installer-functions.sh"
source "$SANDBOX/installer-functions.sh"

curl() {
  local url="${!#}"
  case "$url" in
    */releases/latest)
      [ "$scenario" = stable ] || return 22
      printf '{"tag_name":"v1.0.0"}\n'
      ;;
    */releases\?per_page=1)
      [ "$scenario" = prerelease ] || return 22
      printf '[{"tag_name":"v1.1.0-rc.1"}]\n'
      ;;
    */releases.atom)
      [ "$scenario" != offline ] || return 35
      if [ "$scenario" = limited ]; then
        cat <<'FEED'
<feed xmlns="http://www.w3.org/2005/Atom">
  <id>tag:github.com,2008:https://github.com/ybz21/Roami/releases</id>
  <entry><id>tag:github.com,2008:Repository/1251063272/v1.2.0-rc.2</id></entry>
  <entry><id>tag:github.com,2008:Repository/1251063272/v1.1.0-rc.1</id></entry>
</feed>
FEED
      else
        printf '<feed xmlns="http://www.w3.org/2005/Atom"></feed>\n'
      fi
      # Real release feeds include large changelogs after the first tag.
      local line
      for ((line=0;line<4096;line++)); do printf '<content>Release notes padding</content>\n'; done
      ;;
    *) echo "Unexpected request: $url" >&2; return 1 ;;
  esac
}

scenario=offline
VERSION=v0.5.0
[[ "$(resolve_tag)" = v0.5.0 ]]
VERSION=latest
scenario=stable
[[ "$(resolve_tag)" = v1.0.0 ]]
scenario=prerelease
[[ "$(resolve_tag)" = v1.1.0-rc.1 ]]
scenario=limited
[[ "$(resolve_tag)" = v1.2.0-rc.2 ]]
for scenario in empty offline; do
  if resolve_tag; then
    echo "Release discovery accepted $scenario responses" >&2
    exit 1
  fi
done
echo 'PASS: explicit version, stable priority, prerelease fallback, API rate-limit recovery, empty and offline failures'
