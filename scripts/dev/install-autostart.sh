#!/usr/bin/env bash
# 让 Roami 开机自启（用户级 systemd 服务）。不需要 root。
#
#   bash scripts/dev/install-autostart.sh          装上并立即接管
#   bash scripts/dev/install-autostart.sh remove   卸掉，退回手工 start.sh
#
# 为什么包 start.sh 而不是直接 ExecStart 二进制：
#
# 这台机器上的实例是 start.sh 起的，配置从 .env 读（口令、TOTP、TLS、绑定地址），
# 前端目录由 `-web $(pwd)/frontend/dist` 显式指定。install.sh 里那个服务模板跑的是
# 另一条路（发布版二进制 + ~/.roami/config.yaml + 内嵌前端）。两条路的配置一旦对不上，
# 一次「装个自启」就变成了改口令、改端口、前端回退到编译时快照。
#
# 所以这里只改**谁来拉起**，不改**拉起时带什么**：ExecStart 就是 `start.sh fg`，
# 它内部 exec 的命令行与现在后台跑的那条逐字相同。
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
UNIT_DIR="${HOME}/.config/systemd/user"
UNIT="roami.service"

if [ "${1:-}" = "remove" ]; then
  systemctl --user disable --now "$UNIT" 2>/dev/null || true
  rm -f "${UNIT_DIR}/${UNIT}"
  systemctl --user daemon-reload
  echo "✔ 已卸载。重新手工启动：bash ${REPO}/start.sh"
  exit 0
fi

command -v systemctl >/dev/null || { echo "✘ 无 systemd，装不了自启" >&2; exit 1; }
[ -x "${REPO}/backend/ttmux-web" ] || { echo "✘ 未找到 backend/ttmux-web，先跑一次 bash start.sh --dev" >&2; exit 1; }

mkdir -p "$UNIT_DIR"
cat > "${UNIT_DIR}/${UNIT}" <<UNITFILE
[Unit]
Description=Roami web console
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=${REPO}
# start.sh fg 前台 exec 后端，参数与手工启动完全一致（含 -web frontend/dist）。
ExecStart=/bin/bash ${REPO}/start.sh fg
# tmux server is spawned from the web process; keep its panes alive across web restarts.
KillMode=process
Restart=always
RestartSec=3
# start.sh 在 dist 比源码旧时会先跑一次前端构建（这个前端要一分多钟）。
# 默认的 90s 会把启动判成超时并反复重启，于是永远起不来。
TimeoutStartSec=900

[Install]
WantedBy=default.target
UNITFILE

systemctl --user daemon-reload

# 手工起的那个进程不归 systemd 管，不先停掉就是两个进程抢同一个端口。
if [ -f /tmp/ttmux-web.pid ] || pgrep -f 'backend/ttmux-web' >/dev/null 2>&1; then
  echo "==> 停掉手工启动的实例…"
  bash "${REPO}/start.sh" stop >/dev/null 2>&1 || true
fi

systemctl --user enable --now "$UNIT"

# linger：没登录时也让用户级服务活着（服务器/重启后无人登录的场景必需）。
if command -v loginctl >/dev/null && [ "$(loginctl show-user "$USER" -p Linger --value 2>/dev/null)" != "yes" ]; then
  loginctl enable-linger "$USER" 2>/dev/null \
    || echo "⚠ enable-linger 失败：注销后服务会停。可 sudo loginctl enable-linger $USER"
fi

echo "✔ 已注册开机自启"
systemctl --user status "$UNIT" --no-pager -n 8 2>/dev/null | sed 's/^/  /' || true
echo
echo "  日志: journalctl --user -u ${UNIT} -f"
echo "  卸载: bash $0 remove"
