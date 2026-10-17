#!/usr/bin/env bash
#
# ttmux 端到端测试
# 用法: bash tests/test_ttmux.sh
#

set -euo pipefail

PASS=0
FAIL=0
ROAMI_BIN="${ROAMI_BIN:-roami}"
session_cli() { "$ROAMI_BIN" session "$@"; }
TTMUX=session_cli
TMP="/tmp/ttmux-test-$$"

bold=$'\033[1m'
green=$'\033[32m'
red=$'\033[31m'
dim=$'\033[2m'
reset=$'\033[0m'

pass() { echo -e "  ${green}✔${reset} $1"; ((PASS++)) || true; }
fail() { echo -e "  ${red}✘${reset} $1"; ((FAIL++)) || true; }

cleanup() {
    $TTMUX group kill test-e2e 2>/dev/null || true
    $TTMUX kill test-env-check 2>/dev/null || true
    rm -rf "$TMP"
    # 清理测试 env
    $TTMUX env rm TEST_TTMUX_VAR 2>/dev/null || true
}
trap cleanup EXIT

echo ""
echo -e "${bold}ttmux 端到端测试${reset}"
echo -e "${dim}$(printf '─%.0s' {1..40})${reset}"
echo ""

mkdir -p "$TMP"

# ══════════════════════════════════════
# TEST 1: 基本命令
# ══════════════════════════════════════

echo -e "${bold}[基础]${reset}"

# help
$TTMUX help >/dev/null 2>&1 && pass "help" || fail "help"

# version
ver=$($TTMUX --version 2>&1)
[[ "$ver" == ttmux\ v* ]] && pass "version: ${ver}" || fail "version"

# ls (不崩溃即可)
$TTMUX ls >/dev/null 2>&1 && pass "ls" || fail "ls"

echo ""

# ══════════════════════════════════════
# TEST 2: 全局 env
# ══════════════════════════════════════

echo -e "${bold}[全局 ENV]${reset}"

$TTMUX env set TEST_TTMUX_VAR=hello_ttmux >/dev/null 2>&1
pass "env set"

output=$($TTMUX env 2>&1)
echo "$output" | grep -q "TEST_TTMUX_VAR" && pass "env list" || fail "env list"

echo ""

# ══════════════════════════════════════
# TEST 3: spawn 并行 + 组装
# ══════════════════════════════════════

echo -e "${bold}[并行任务: spawn → status → collect → 组装]${reset}"

# 创建 3 个并行任务，各写一个文件片段
$TTMUX spawn test-e2e \
    "header" "echo '<!DOCTYPE html><html><head><title>test</title></head>' > ${TMP}/header.html" \
    "body"   "echo '<body><h1>Hello</h1></body>' > ${TMP}/body.html" \
    "footer" "echo '</html>' > ${TMP}/footer.html" \
    >/dev/null 2>&1
pass "spawn 3 个任务"

# 等文件生成
sleep 2

# 检查 status
status_output=$($TTMUX status test-e2e 2>&1)
echo "$status_output" | grep -q "test-e2e" && pass "status 可查" || fail "status 不可用"

# 检查文件是否都生成了
all_exist=true
for f in header.html body.html footer.html; do
    [[ -f "${TMP}/${f}" ]] || { all_exist=false; break; }
done
[[ "$all_exist" == true ]] && pass "3 个文件全部生成" || fail "文件缺失"

# 组装
cat "${TMP}/header.html" "${TMP}/body.html" "${TMP}/footer.html" > "${TMP}/page.html" 2>/dev/null
[[ -f "${TMP}/page.html" ]] && grep -q "Hello" "${TMP}/page.html" \
    && pass "组装成功" || fail "组装失败"

# collect
collect_output=$($TTMUX collect test-e2e 2>&1)
[[ -n "$collect_output" ]] && pass "collect 有输出" || fail "collect 无输出"

# 清理
$TTMUX group kill test-e2e >/dev/null 2>&1
pass "group kill 清理"

# 验证清理干净
$TTMUX group ls 2>&1 | grep -q "test-e2e" && fail "清理不干净" || pass "清理干净"

echo ""

# ══════════════════════════════════════
# TEST 4: env 注入验证
# ══════════════════════════════════════

echo -e "${bold}[ENV 注入]${reset}"

$TTMUX spawn test-e2e \
    "env-check" "env | grep TEST_TTMUX_VAR > ${TMP}/env-result.txt" \
    >/dev/null 2>&1

sleep 2

if [[ -f "${TMP}/env-result.txt" ]] && grep -q "hello_ttmux" "${TMP}/env-result.txt"; then
    pass "env 自动注入到新 session"
else
    fail "env 未注入 (${TMP}/env-result.txt)"
fi

$TTMUX group kill test-e2e >/dev/null 2>&1

# 清理测试用 env
$TTMUX env rm TEST_TTMUX_VAR >/dev/null 2>&1
pass "env rm 清理"

echo ""

# ══════════════════════════════════════
# TEST 5: JSON 输出
# ══════════════════════════════════════

echo -e "${bold}[JSON 输出]${reset}"

json=$($TTMUX ls --json 2>&1)
echo "$json" | python3 -c "import sys,json; json.load(sys.stdin)" 2>/dev/null \
    && pass "ls --json 合法 JSON" || fail "ls --json 非法"

echo ""

# ══════════════════════════════════════
# 汇总
# ══════════════════════════════════════

echo -e "${dim}$(printf '─%.0s' {1..40})${reset}"
total=$((PASS + FAIL))
if [[ $FAIL -eq 0 ]]; then
    echo -e "${green}${bold}全部通过${reset} ${dim}(${total}/${total})${reset}"
else
    echo -e "${red}${bold}${FAIL} 个失败${reset} ${dim}(${PASS}/${total} 通过)${reset}"
fi
echo ""

exit $FAIL
