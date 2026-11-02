# 本地网关与 Agent 独立计费：设计稿验收

2026-11-01，基线 `5d66fbe8`。交付为 [单文件 HTML](gateway-billing-v1.html)，包含 Product Design、User Stories、Technical Design 和四组可操作示例；不修改产品代码、线上 Key、Agent 配置或账本。

## 核心设计

- 复用 Roami 已配置模型源；本机已有 CLI 连接可显式导入，OAuth / 凭据助手不冒用导入。
- 默认各 Agent 类型使用独立接入身份和 Key；支持同类多个命名接入。V2 再给托管会话签发独立临时 Key；共享 Key 的外部进程不伪装成会话分账。
- 归账身份来自 Key 的服务端绑定，不信任客户端 Agent / 会话 header。轮换 Key 不拆身份，停用不删历史。
- 费用沿用 Go 网关原始用量和快照；缺失用量、未定价、明确零价分开表达。计费为本地核算，不承诺上游扣款或收款。

## 已验证

- `node --check`：内联脚本语法通过。
- 桌面 Chrome：5 个章节切换；原厂模式能真正隐藏网关表单；导入分支先禁用应用；演示导入、选择身份与模型后应用，当前模型更新。
- Key：轮换“OpenCode · 项目 A”后身份不变；停用后仍能筛选它的历史。演示字符串以 `demo_only_` 标识，不能用于真实鉴权。
- 账本：6 条示例调用，5 条已知、1 条待核账；已知 Token 192,000，已知费用 CNY 0.3600。OpenCode 筛选为 4 条调用、CNY 0.2240；项目 A 为 CNY 0.1020，另有 1 条待核账。
- 单文件无外部依赖，浏览器资源检查除 favicon 外 0 条外部请求；原型不调用产品 API、不持久化密钥。
- Android Redmi Note 8（216d6a43），392 CSS px：ADB 真实点按切换 Agent 接入 / 费用账本；真实滑动后主滚动区 scrollTop 从 0 变为 340.36 和 413.45；文档无横向溢出，导航宽度与 scrollWidth 均为 393，账本横向溢出只留在表格内部。
- 表单、标签和动作不少于 44px，hover 限 fine pointer，图标没有使用 emoji / 文字符号；流程图用 CSS 连线与文本节点。
- 本稿为中文开发评审文档；正式产品文案使用现有中英 i18n。未改 `frontend/src` 或运行代码，不运行无关的 Go / Python / 前端构建测试。

桌面截图：`/tmp/roami-gateway-billing-overview-desktop.png`、`/tmp/roami-gateway-billing-connect-desktop.png`、`/tmp/roami-gateway-billing-ledger-desktop.png`。
手机截图：`/tmp/roami-gateway-billing-connect-phone.png`、`/tmp/roami-gateway-billing-ledger-phone.png`。
截图为临时验收产物，不提交到主分支。正式实现仍需验证实际 OpenCode 版本的配置覆盖、Key 注入、真实鉴权与协议 / 计费往返；本稿不会把原型操作当作这些能力已实现。
