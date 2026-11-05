#!/usr/bin/env bash
set -euo pipefail

case "${1:-}" in
  presentation|tabular) programs=() ;;
  market) programs=(soffice pdftoppm pdffonts fc-match) ;;
  video) programs=(ffmpeg ffprobe) ;;
  *) echo 'Expected presentation|tabular|market|video' >&2; exit 2 ;;
esac
for program in "${programs[@]}"; do
  command -v "$program" >/dev/null || { echo "Missing $1 dependency: $program" >&2; exit 1; }
done
