# 设计原型验证

2026-10-30。范围是本目录的交互提案和模拟数据，不是正式模型接入验收。

## 产物与复现

- `README.md`：Product Design、User Stories、Technical Design、迁移阶段及资料依据。
- `index.html`：独立 HTML，内联脚本、样式和图标，可离线打开；不依赖测试服务。
- `assets/prototype.tsx`、`prototype.css`、`build.mjs`：可维护原稿和构建入口，复用项目图标、`useLayout()`、主题令牌及 antd。
- 原型为中文设计文档，属于内部设计稿的语言例外。正式 UI 接入时必须使用项目全局中英 i18n，不能直接搬入硬编码文案。

```bash
cd frontend && npm ci --no-audit --no-fund
cd ..
node docs/design/20261030-智能体模型切换/assets/build.mjs
frontend/node_modules/.bin/tsc -p docs/design/20261030-智能体模型切换/assets/tsconfig.json
node --check docs/design/20261030-智能体模型切换/assets/build.mjs
```

静态预览通过 `scripts/dev/isolated-roami.sh /tmp/roami-model-switch-validation ...` 启动；按同一入口 `--stop` 清理测试 tmux 服务器。没有修改真实 Agent 的配置、凭据、模型路线或用户任务。

## 桌面浏览器

使用 `roami chrome` 独立标签验证：

| 检查 | 结果 |
| --- | --- |
| 单工具切换、首次确认、成功反馈 | 通过，文案为默认已设置，不冒充运行会话已切换 |
| 恢复原配置 | 通过，恢复后显示使用原配置及可能需要登录的提示 |
| 连接不兼容 | Codex 选择仅 Chat Completions 的本地连接后禁用应用，保留换连接入口 |
| 返回保留草稿 | 选择 OpenRouter 后返回列表，再打开仍为 OpenRouter |
| 外部配置冲突 | 读取前禁止应用，读取后展示当前文件与所选配置，明确选择后才解除阻断 |
| 批量部分失败 | Codex 显示默认已设置，Claude 显示冲突，整体显示部分完成；可进入单项处理 |
| 深浅主题 | 主题令牌切换正常；检查桌面深色和窄屏浅色画面 |
| 原型与产品隔离 | 浏览器资源记录未出现 `/api/` 请求；模型测试和写入均为页面内模拟 |

七档截图过程中使用 ResizeObserver 读取实际档位和几何数据：320 / 390 为 compact、820 为 medium、1100 为 expanded、1280 / 1600 / 1920 为 large。全部 `scrollWidth <= innerWidth`，文档高度等于视口高度。手机档有上下栏，页面内容在自己的容器滚动。

## Android 真机

Redmi Note 8，Android Chrome 154，392 CSS px 宽、DPR 2.75，实际物理屏幕 1080×2340。通过 LAN 打开原型，`data-size=compact`、`data-pointer=coarse`。

- 用 `roami adb` 实际点按 Codex 切换、模型来源、OpenRouter、应用与确认；读取到成功文案及当前来源 OpenRouter。
- 实际滑动详情页，详情容器 scrollTop 从 0 变为约 149，再滑至恢复入口；文档 scrollTop 始终为 0。
- 实际点按恢复、恢复确认，读取到“已恢复接管前模型配置”，当前值回到“使用原配置”。
- Android 系统返回回到模型列表；上下栏仍在，未出现双重返回栏，页面无横向溢出。

手机 Chrome 的浏览器 WebSocket 路径不带实例 ID，当前 `roami chrome` 返回 `CHROME_BROWSER_IDENTITY_UNAVAILABLE`。因此真机触控与截图使用 `roami adb`，仅页面状态和几何读取使用直接 CDP。使用稳定页面 ID 定位，并在每组 ADB 操作前激活本任务页面；没有改动该 CLI 的身份校验。

## 检查边界

构建、设计原稿 TypeScript 检查和构建脚本语法检查通过。更改范围为设计文档和演示资产，未修改 `frontend/src`、后端或 Python，因此不以产品全量测试代替设计验证，也不声称运行时已经接入。落地仍须执行 README 中的真实 CLI、协议兼容、配置事务与仓库正式前端门禁。

截图留在 `/tmp/model-switch-*.png`，作为本次评审展示材料，不提交到主分支；若后续创建 PR，按仓库 `pr-shots` 流程上传。
