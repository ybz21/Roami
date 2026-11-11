# 验收记录

日期：2026-11-11。

- skills.sh 实际响应返回 19 项可通过现有固定版本流程安装的仓库技能，保留累计安装量。
- 前端全量测试最终 226 个测试文件、1,621 项通过；市场测试包含 9 项，覆盖默认热门、搜索返回热门、安装目标、失败保留选择与既有导入行为。
- 市场与 Agent 命令后端回归最终 45 项通过，包含 HTTP prepare/install 全流程、所有目标实际文件、附带脚本保留、重复安装、同名保护、写失败回滚、无效目标和失效回执。
- 实际 Android Redmi Note 8（392 CSS px，coarse）通过 ADB 点按打开技能、修改目标并安装到隔离 Roami 节点；核对持久记录中的 Git commit 和完整文件。ADB 滑动使市场 `scrollTop` 从 0 增至 286，文档无横向溢出，顶栏与底部四入口保留；系统返回键关闭详情后保留市场路由与原列表。四个安装目标高度均为 44px，命中测试通过。
- 独立 Chromium 的 fine 指针下，1280 / 1920 / 2560 / 3440 CSS px 均通过侧栏展开 / 收起检查，无文档横向或纵向溢出；收起时网格为 3 / 5 / 7 / 10 列，展开侧栏后释放给内容的宽度同步调整。
- 桌面实际键入不触发搜索，提交后展示结果，并可返回热门；英文界面通过。搜索使用捕获的实际上游响应，详情布局使用已下载的固定版本内容，避免上游瞬时超时影响布局验收。真机预览与安装未替换响应。
- Android ADB 实际点按首页、项目、设置、工具均到达对应路由，并从工具打开能力。
- 临时实例经 `isolated-roami.sh /tmp/roami-popular-skills` 启动；测试写入隔离节点或临时目录，未向用户实际 Agent 技能目录安装示例。

前端 typecheck、i18n / hover 审计、全量 Vitest 与生产构建通过。生产构建保留已有大文件分块提示。

截图（临时文件）：`/tmp/popular-skills-desktop.png`、`/tmp/popular-skills-desktop-en.png`、`/tmp/popular-skills-phone.png`、`/tmp/popular-skills-install-phone.png`。

`scripts/dev/quality/check.sh quick` 已通过：Go 全量测试、Python lint / format、4,799 项 Python 测试（48 项跳过、6 项子测试通过）、前端审计 / 类型检查、secret scan 与文件策略均通过。新增 HTTP 回归另以最终代码重跑市场与 Agent 命令共 45 项通过。

本次测试 Web / Agent / Chrome 进程、手机测试标签与 ADB 转发已关闭，隔离 tmux 服务仅通过同一启动入口的 `--stop` 回收。
