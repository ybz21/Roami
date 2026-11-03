# 未知费用仅提示、不阻断调用

## Product Design

用户明确允许未知费用只提示、不阻断调用。每日限额只对已确认消费生效；未知金额不计入限额，不能据此判断实际消费没有超额。已有未知费用、错误码、回执和核账入口保留，不补造 token、不归零、不改日限额数值。核账后的金额继续参与准入判断。

## User Stories

某次网络中断缺失用量时，我仍能继续使用 Claude、Codex、OpenCode 和 Roami，在计费页看到待核账提示，并在取得账单后补录真实费用。

## Technical Design

`Ledger.Admit` 不再依据 `state=unknown` 拒绝准入，仍在同一事务内检查已确认消费与 pending 请求。账目结算、崩溃恢复、原始请求失败和协议错误处理保持现有语义。计费页使用普通提示展示未知费用，并明确说明不会阻断调用、未计入限额；每日限额提示同步说明只计算已确认费用。

部署以当前已上线的 OKR 源码树 `2f34604fc2df1ee45834beaf7e23345bd3a786cc` 叠加本补丁，保留完整 OKR 功能、现有 Python runtime 路径、模型路由、单价、100 CNY 日限额和所有历史账目。已与 OKR 会话确认无更新的上线树。

## Acceptance

- 使用旧版 `ledger.go` 的 Go overlay 运行新增限额回归，两个场景均因 `MODEL_PROXY_USAGE_UNKNOWN` 失败。
- 新回归覆盖未知账后跨 Agent 连续准入、费用和 token 持续未知、已确认费用达到限额拒绝，以及人工核账后金额计入限额；既有并发在途准入、拒绝响应结算与禁止自动重放检查保留。
- 本补丁 `scripts/dev/quality/check.sh full` 与前端 167 文件、1,220 项测试通过；OKR 整合源码树的 Go 全量、前端 typecheck / i18n / hover、173 文件 1,248 项测试和生产构建通过。无 Python 改动，按范围跳过 Python 检查。
- 隔离 HTTPS 服务使用未知费用、100 CNY 日限额的离线账目夹具验证提示。桌面中文深色与英文浅色通过；Redmi Note 8 经 LAN 使用 ADB 真实登录、查看提示和滚动，`data-size=compact`、`data-pointer=coarse`，未知提示使用普通提示样式、限额仍为 100。滚动位置从 0 增至 376.73，文档滚动为 0，无横向溢出，顶部与底部导航保留。
- 截图 `/tmp/roami-unknown-before-desktop.png`、`/tmp/roami-unknown-after-desktop.png`、`/tmp/roami-unknown-after-desktop-en.png`、`/tmp/roami-unknown-after-phone.png` 不提交进主分支。离线夹具验收不请求付费上游，不修改生产账目。
- 本机已部署整合树 `0896117bcfa58c9c35240f27fc9cde5adad6778c`，版本 `okr-usage-0896117b`。原生 Claude Code 使用原配置执行一轮无工具调用，成功返回 `OK`；网关账本 HTTP 200、1,558 输入 / 2 输出 token、正常结算。原 12:06 网络失败账目仍为 unknown、费用和 token 均为空，没有核账或归零。100 CNY 限额、路由、单价、Python runtime 环境文件均核对未改动，OKR 源码完整保留。
