# 排查与方案验收

以任务工作区源码 `001649fb` 和 2026-11-21 用户提供的 DevTools 截图为依据。截图可见成批的
`codex`、`opencode`、多条 50 行抓屏、两条相同可见参数的字节游标转录和一条 `agents`。
截图裁切了完整 URL 及 Initiator，Keep log 已开启。原件用于本地核对，保留在原路径。

## 受控计时

临时 Vitest/jsdom 用例调用现有 `useTerminalRuntime`、`useAgentKinds`、`TerminalPane`、
`PromptPanel` 和 `useTranscript`。将底层 API 替换为即时、固定响应，终端画布用空组件替代以避免连接
PTY。各场景分别清除挂载调用，推进虚拟时间 30,000 ms，统计 `(0, 30s]` 内的指定路径。

| 受控场景 | 结果 |
| --- | --- |
| 8 个桌面 CLI 标签 | `/claude`、`/codex`、`/opencode` 各 48 次，共 144 次 |
| 同页两个 `useAgentKinds` 消费者 | `/sessions/agents` 共 5 次 |
| 8 标签的终端面板，外层折叠为零宽 | 标签检查合计 56 次，活跃标签的 `PromptDialog` 额外 25 次 |
| 同会话的 1.5 秒和 6 秒转录订阅，挂载后设置 `document.hidden` | 同样的字节游标请求 20 + 5 次，已挂载的 `PromptPanel` 另抓屏 25 次 |
| 挂载 1 秒后以相同的 8 个会话名传入新数组 | 在 5 秒周期到达前立即再发 24 次探测 |

四项测试通过，其中第一项测试同时验证 Agent 探测和共享批量查询。数字用于验证当前渲染层的请求生成机制。
真实生产流量、后端负载和实施后的改善幅度留待方案中的固定窗口对照验证。

## 交付检查

- 用 Roami Chrome 打开总览、场景与验收、技术方案，点按页面入口和返回链接。
- 三页分别以 390、1280、1920、2560、3440 CSS px 检查，共 15 个布局，均无横向溢出，正文在独立区域滚动。
- 校验 HTML 内相对链接和样式、图标共 18 个目标，均返回 HTTP 200。
- `scripts/dev/quality/check.sh quick` 通过。本次交付为设计文档，Android 真机行为和生产负载属于实施验收。
