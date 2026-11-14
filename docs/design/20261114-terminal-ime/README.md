# 终端中文输入完整性

## 产品设计

终端确认候选词后立即提交，应保留完整文字；输入法切换、连续确认相同词和拖放文件不能丢弃已有输入。沿用现有界面，不新增控件或文案。

## 用户故事

- 输入“合并”并立即按 Enter，程序收到完整的“合并”。
- 连续确认两次“一次”，程序收到“一次一次”，不把用户重复输入当作重复事件。
- 输入法切换提交 `s c p` 后紧接着输入 `!`，保留已有拼音修正并收到 `scp!`。
- 拖放文件时保留仍在组合或等待提交的中文；未组合时仍清除原生 drop 残留。

## 技术设计

`terminal-ime.ts` 负责 xterm 5.5 的输入兼容、提交转发和 drop 残留清理，`Terminal.tsx` 只把已完成的数据转发给当前 WebSocket。

根因有两处：`compositionend` 时记录的 textarea 长度可能早于浏览器最终替换候选词，随后的 Enter 使用旧长度同步 finalize，把“合并”截成“合”；组件另设的 `composing` 标记又可能在 xterm 已同步完成组合时仍为 true，将合法文本与 Enter 一起丢弃。

同步 finalize 前重新读取 textarea 末尾；直接转发 xterm 完成的输入，不再使用第二套组合标记过滤 `onData`。拼音修正仅替换匹配本次候选词的前缀，保留同批后续文本，并在本次延迟 finalize 后过期。drop 使用 xterm 的组合状态与等待提交状态，避免清除尚未发出的文字。卸载时恢复兼容补丁并移除订阅与定时器。

## 验收

- 在旧代码上新增回归用例，确认预期 `合并\r` 实际输出 `合\r`。
- 隔离实例：`scripts/dev/isolated-roami.sh /tmp/roami-ime-oul3 ...`；仅创建测试会话，使用逐行回显与 JSONL 记录核对真实 PTY 输入。
- 桌面 Chrome 与 Redmi Note 8 的 Chrome 通过 HTTPS 访问隔离实例，受控重放候选词最终替换与 Enter 的事件顺序；旧代码两端实际收到“合”，修复后核对完整文字。
- 使用 CDP 原生 IME 输入接口补验中文提交，并检查普通英文、连续相同词、拼音尾随输入与直接插入文本。事件重放验证竞态，不代表所有操作系统输入法均已人工测试。
- 12 项 xterm 输入回归测试；全量前端 253 个文件、1,827 项测试通过。
- `scripts/dev/quality/check.sh quick`、`full`；前端 typecheck、i18n、hover、构建。
- 截图通过 `scripts/dev/pr-shot.sh` 保存到 `pr-shots`；测试脚本、输入记录与截图保留在 `/tmp/roami-ime-oul3/`，不提交一次性截图或凭据。
