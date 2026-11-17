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

## 2026-11-15：标点误删

### 产品设计与用户故事

沿用会话终端界面，输入“完整文字”再打逗号，应收到“完整文字，”。连续标点不重复、不吞字；真实退格仍删除一个字；候选词内的编辑只影响尚未提交的候选词。

### 技术设计

xterm 5.5 在非组合状态收到 `keyCode=229` 时，用延迟任务比较 textarea 新旧长度。输入法把残留候选词替换成更短的标点，会触发 `DEL`；多个延迟任务也会重复转发同一份后续内容。

`terminal-ime.ts` 替换这条非组合输入回退：标记当前 IME 按键，通过真实 `input` 的 `insertText` / `deleteContentBackward` 分别发送文字或退格，不再根据 textarea 长度推断删除。下一次按键或组合开始时清除标记；keypress 已处理的字符不重复转发。保留 xterm 的组合提交与读屏模式路径，卸载时恢复被替换的方法。

### 验收

- 新增回归在旧代码上出现 11 项失败：八种中英文标点误发 `DEL`，连续标点多发，textarea 清空误删，下一次组合吞掉标点。
- 隔离实例 `/tmp/roami-punctuation-a6rL/`，桌面 Chrome 和 Redmi Note 8 Chrome 经 HTTPS 访问真实会话；事件重放后，旧构建的 PTY 均收到“完整文”。不将事件重放视为所有系统输入法均已人工验证。
- 修复构建两端各核对 14 条 PTY 回执：八种中英文标点、连续重复标点、IME 删除、标点接下一次组合、立即 Enter、CDP 原生组合与直接插入、普通键盘及 Backspace，全部符合预期。
- Redmi Note 8 使用豆包输入法，ADB 真实坐标点按输入 `wenzi`、选择“文字”、连续输入两个逗号、退格一次、换行，PTY 收到“文字，”。记录的原生事件为 `keyCode=229` 与 `insertText`，未合成输入事件。
- 桌面 1280 / 1920 / 2560 / 3440 CSS px、手机 compact/coarse 检查无文档横向溢出；软键盘打开后可输入、退格与换行。
- 29 项 xterm 回归和全量前端 255 个文件、1,858 项测试通过；`quality/check.sh full` 包含 typecheck、i18n、hover 与生产构建，Python/Go 按变更范围跳过。
- 本次脚本、PTY 回执、原生事件、门禁日志及前后截图保留在 `/tmp/roami-punctuation-a6rL/`，截图通过 `pr-shots` 展示；不提交测试凭据或构建产物。
