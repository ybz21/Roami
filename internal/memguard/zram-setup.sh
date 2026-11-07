#!/usr/bin/env bash
set -euo pipefail

size="${1:-}"
[[ "$size" != --* ]] || size=""
if [[ -n "$size" ]]; then shift; fi
memory_limit=""
dry_run=false
while (($#)); do
  case "$1" in
    --memory-limit) [[ $# -ge 2 ]] || exit 2; memory_limit="$2"; shift 2 ;;
    --dry-run) dry_run=true; shift ;;
    *) echo "Usage: sudo bash roami-zram-setup.sh [16G] [--memory-limit 4G] [--dry-run]" >&2; exit 2 ;;
  esac
done
total_kb=$(awk '/MemTotal:/ {print $2}' /proc/meminfo)
size="${size:-$((total_kb / 2048))M}"
memory_limit="${memory_limit:-$((total_kb / 8192))M}"
for value in "$size" "$memory_limit"; do
  [[ "$value" =~ ^[1-9][0-9]*[MG]$ ]] || { echo "Expected a positive size such as 16G or 4096M" >&2; exit 2; }
done
if $dry_run; then
  printf 'zram size=%s memory_limit=%s algorithm=zstd priority=100\n' "$size" "$memory_limit"
  exit 0
fi
[[ $(id -u) == 0 ]] || { echo "Administrator required: sudo bash roami-zram-setup.sh" >&2; exit 1; }
for command in modprobe zramctl mkswap swapon swapoff systemctl; do command -v "$command" >/dev/null; done
if [[ -r /sys/module/zswap/parameters/enabled ]] && [[ $(cat /sys/module/zswap/parameters/enabled) == Y ]]; then
  echo "zswap is already enabled; keeping the existing compression backend." >&2
  exit 1
fi
if swapon --noheadings --raw --show=NAME | grep -q '^/dev/zram'; then
  echo "A zram swap device is already active; leaving it unchanged."
  exit 0
fi

cat > /usr/local/sbin/roami-zram <<'RUN'
#!/usr/bin/env bash
set -euo pipefail
source /etc/roami-zram.conf
state=/run/roami-zram.device
case "${1:-}" in
  start)
    if [[ -f "$state" ]]; then
      dev=$(cat "$state")
      if swapon --noheadings --raw --show=NAME | grep -Fxq "$dev"; then exit 0; fi
    fi
    modprobe zram
    dev=$(zramctl --find --size "$SIZE" --algorithm zstd)
    cleanup() {
      if swapon --noheadings --raw --show=NAME | grep -Fxq "$dev"; then return; fi
      zramctl --reset "$dev" || true
      rm -f "$state"
    }
    trap cleanup ERR
    echo "$MEMORY_LIMIT" > "/sys/block/${dev##*/}/mem_limit"
    mkswap "$dev" >/dev/null
    printf '%s\n' "$dev" > "$state"
    swapon --priority 100 "$dev"
    trap - ERR
    ;;
  stop)
    [[ -f "$state" ]] || exit 0
    dev=$(cat "$state")
    [[ "$dev" =~ ^/dev/zram[0-9]+$ ]] || exit 1
    # A failed swapoff must retain both the active device and its ownership record.
    swapoff "$dev"
    zramctl --reset "$dev"
    rm "$state"
    ;;
  *) exit 2 ;;
esac
RUN
chmod 755 /usr/local/sbin/roami-zram
printf 'SIZE=%q\nMEMORY_LIMIT=%q\n' "$size" "$memory_limit" > /etc/roami-zram.conf
chmod 600 /etc/roami-zram.conf
cat > /etc/systemd/system/roami-zram.service <<'UNIT'
[Unit]
Description=Roami compressed swap
After=systemd-modules-load.service

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/usr/local/sbin/roami-zram start
ExecStop=/usr/local/sbin/roami-zram stop
TimeoutStopSec=120

[Install]
WantedBy=multi-user.target
UNIT
systemctl daemon-reload
systemctl enable --now roami-zram.service
swapon --noheadings --raw --show=NAME | grep -q '^/dev/zram'
echo "Compressed swap enabled; compression ratio depends on the workload."
zramctl
swapon --show
