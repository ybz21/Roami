#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../../.."

if [ "$#" -ne 1 ]; then
  echo 'Expected presentation|tabular|market|video' >&2
  exit 2
fi
case "$1" in
  presentation) directory=skills/presentation-edit ;;
  tabular) directory=skills/tabular-analysis ;;
  market) directory=skills/market-series-report ;;
  video) directory=skills/video-assembly ;;
  *) echo 'Expected presentation|tabular|market|video' >&2; exit 2 ;;
esac

if [ "$1" = market ]; then
  for program in soffice pdftoppm pdffonts fc-match; do
    command -v "$program" >/dev/null || { echo "Missing market report dependency: $program" >&2; exit 1; }
  done
fi
if [ "$1" = video ]; then
  for program in ffmpeg ffprobe; do
    command -v "$program" >/dev/null || { echo "Missing video assembly dependency: $program" >&2; exit 1; }
  done
fi

lint_paths=("$directory")
if [ "$1" = market ]; then lint_paths+=(cases/case-99-mech-mp01/scripts); fi
uv run --project agent-runtime --frozen ruff check "${lint_paths[@]}"
uv run --project agent-runtime --frozen ruff format --check "${lint_paths[@]}"
if [ "$1" = market ]; then
  uv run --isolated --with 'pandas>=2.2,<4' --with 'matplotlib>=3.8,<4' --with 'python-pptx>=1,<2' --with pytest pytest -q -p no:cacheprovider "$directory/tests"
else
  uv run --project agent-runtime --frozen pytest -q -p no:cacheprovider "$directory/tests"
fi
