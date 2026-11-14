# 设计原型验收

2026-11-14。范围仅限本目录的文档与独立原型；产品导航尚未实现，不把演示状态当作产品功能验收。

## 已核对

- 已阅读用户附件原件 `/tmp/clipboard-20261114-234935-6l3x.png`，未改写原图。
- 已追踪 `ProjectTree` 到 `returnToTask` 的导航语义，核对 `FileTab.task` 和全局平铺标签约定。
- 已构建设计 JS 并在真实 Chrome 打开，无页面脚本错误。HTML / CSS / JS 使用相对资源，无网络字体、CDN 或 API 请求。
- 已检查深浅主题；图标和档位直接复用项目 `icons.tsx` / `useLayout()`。
- 交互实际点按：会话直达、文件直达、折叠不切换、切组恢复、文件草稿保留、对话草稿保留、文件返回来源对话、浏览器返回均通过。

## 桌面尺寸

高度 900 CSS px。每个宽度分别检查右栏展开与收起，文档没有横向或纵向溢出，主内容高度均约 728.8 CSS px。

| 视口宽度 | 右栏展开时内容宽度 | 右栏收起时内容宽度 |
| --- | --- | --- |
| 1280 | 740 | 1000 |
| 1920 | 1380 | 1640 |
| 2560 | 2020 | 2280 |
| 3440 | 2900 | 3160 |

另在 1280 × 800 截取交付截图。右栏关闭后主内容得到完整的 260 CSS px，不留空列。

## Android 真机

Redmi Note 8，设备 `216d6a43`，Chrome 经 LAN 打开静态设计原型。实际档位为 `compact` / `coarse`，视口与文档宽度均为 392 CSS px。

- 已截图检查工作区资源二级页、文件全屏页和对话页。
- `roami adb ... shell input tap 300 930` 点文件行，实际进入 `交互方案.md`，标题显示所属工作区。
- `roami adb ... shell input tap 88 450` 点文件标题前的返回箭头，实际进入原对话，出现对话输入区。
- 文件行视觉高度 56 CSS px；返回图标视觉为 32，粗指针伪元素扩为 44 命中区，中心命中返回按钮。
- 文件页没有叠加底部主导航，手机不显示桌面横向标签栏；未出现横向溢出。

手机 Chrome 不提供 Roami 浏览器身份，CLI 的 `--cdp` 读取返回 `CHROME_BROWSER_IDENTITY_UNAVAILABLE`；改用仓库验收清单里的 CDP 读取与截图，触控操作仍通过 `roami adb` 完成。没有操作用户既有业务页面。

## 检查和证据

- `scripts/dev/quality/check.sh quick`：通过（含既有前端 typecheck、i18n 和 hover 检查）。
- Impeccable detector：`[]`，退出码 0。
- `git diff --check`：通过。
- 新增设计源文件没有使用 emoji 或文字图标；按要求扫描了 `frontend/src`，本次没有修改该目录，已有命中不在本提案中迁移。
- 本次只修改设计文档与设计原型资源，不改 `frontend/**`、Go 或 Python；没有以运行产品全套测试代替设计评审。

本机证据保留在 `/tmp/session-nav-browser-results.json`、`/tmp/session-nav-quality.log`、`/tmp/session-nav-desktop.png`、`/tmp/session-nav-light.png`、`/tmp/session-nav-phone-resources.png`、`/tmp/session-nav-phone-file.png`、`/tmp/session-nav-phone-chat.png`。截图通过 `pr-shot.sh` 上传到 `pr-shots`，不提交到主分支。

## 待产品实现后验收

真实文件编辑器的位置恢复、未保存关闭保护、会话失效回退、多会话来源、跨节点、完整中英显示、键盘与安全区、会话派生关系和服务端工作区状态迁移，均为后续产品实现的验收项，不在本次模拟原型中宣称完成。
