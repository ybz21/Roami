# PDF 整页适配与跳页

## 产品设计

PDF 预览默认显示完整单页，同时提供“适合宽度”和 25%～400% 缩放。保留上一页、下一页，以可编辑页码代替只读页码；输入后回车或离开输入框跳转。单页文件隐藏分页，保留缩放。

桌面工具栏居中排列；窄预览区自动分为分页、缩放两行。手机按钮、输入框、缩放选项的触控高度至少 44px，不改变既有返回栏与下载入口。

## 用户故事

- 查看竖版报告或横版演示时，不用滚动也能看到整页边界。
- 需要阅读小字时，切换到适合宽度或放大后在预览区内滚动。
- 长 PDF 可以直接输入目标页码；越界值定位到第一页或末页，空值和非整数恢复当前页。
- 调整窗口、分栏高度或翻到不同尺寸的页面后，当前适配模式继续生效。

## 技术设计

修改共享组件 `frontend/src/components/documents/PdfDocument.tsx`，文件、聊天附件、任务产物和 Office 转 PDF 入口统一生效，无新增接口或依赖。

- `ResizeObserver` 同时读取预览区宽、高；整页比例取宽高比例中的较小值，宽度模式只按宽度计算，百分比模式使用固定比例。
- 每页独立读取 PDF viewport，支持横竖版混排。
- Ant Design `Input` 处理页码草稿与提交，`Select` 提供适配及百分比选项。聚焦页码时选中现值，Escape 恢复当前页。
- 翻页重置内部滚动位置。缩放不以 CSS 压缩画布，放大后允许在预览区内滚动。
- 沿用稳定滚动条、离屏绘制、过期渲染取消和 800 万像素上限，重绘期间保留已完成画面。
- 样式集中在 `document-preview.css`，新增文案同时进入中英文语言包。

## 验收证据

2026-10-30，独立实例 `/tmp/roami-pdf-navigation-check`，通过 Vite 加载工作区真实组件；六页临时 PDF 交替使用 600×900 和 900×600 页面，手机入口为真实 `MobileFilePreview`。

| 检查 | 结果 |
| --- | --- |
| 桌面整页显示 | 1920×993 视口内，纸张为约 626.7×940，完整落在工具栏下方的 940px 阅读区 |
| 窄桌面预览区 | 420×400 容器下工具栏分行，纸张约 202×303，完整显示 |
| 防闪烁 | 静置两秒，canvas 属性变化 0 次 |
| Android 真机 | Redmi Note 8，compact/coarse，文档无横向溢出，按钮命中检查通过 |
| 手机真实点按 | 上一页/下一页、缩放按钮及适配菜单可操作，菜单项高度 44px |
| 手机跳页 | ADB 点按页码、输入 5、确认后定位第 5 页，输入框失焦并收起键盘 |
| 手机滚动 | 100% 放大后 ADB 上滑，scrollTop 从 0 增至约 337，画面持续可见 |
| 手机返回 | ADB 点按返回后关闭二级页，返回栏数量归零 |
| 中英文与主题 | 桌面中文深色、英文浅色；手机中文和英文均无工具栏溢出 |
| 组件回归 | 8 条：保留画面、取消旧渲染、切换文件、高度变化、宽度适配与放大、跳页校验、单页工具栏、横竖版切换 |
| 前端全量 | 147 文件、1108 用例通过；typecheck、i18n、hover 和生产构建通过 |
| 仓库门禁 | quick、full 均通过；无 Python 相关改动，按规则跳过 Python 检查 |

全量测试默认并发运行曾遇到超时；使用 `npx vitest run --maxWorkers=4 --minWorkers=1` 重跑全部通过，没有调整产品代码或超时阈值。

手机 `roami chrome --cdp` 返回 `CHROME_BROWSER_IDENTITY_UNAVAILABLE`，因此使用 `roami adb` 操作真机，并通过该设备的 CDP 读取布局和状态。测试期间有其他页面争用手机前台，最终触控记录在每次操作前明确激活本测试标签。

一次性截图、触控脚本、临时 PDF 与检查日志保存在 `/tmp/roami-pdf-navigation-check/`，不提交进主分支。主要文件：`desktop-before.png`、`desktop-after.png`、`desktop-en-light.png`、`phone-after.png`、`phone-en-after.png`、`phone-scroll.png`、`phone-touch.log`、`phone-scroll.log`、`vitest.log`、`quality-quick.log`、`quality-full.log`。
