# 验收记录

日期：2026-11-05。测试实例通过 `scripts/dev/isolated-roami.sh /tmp/roami-sidebar-acceptance …` 启动，使用私有 tmux socket 与独立数据目录；未以用户会话作为测试数据。

## 界面与交互

| 范围 | 证据与结果 |
| --- | --- |
| 桌面 1280 / 1920 / 2560 / 3440 CSS px | 真实 ProjectTree 组件与隔离样例；工作区副标题为「工作区 · 2 个会话」，父级无运行点；子会话横向缩进，文档无横向溢出 |
| 选中与键盘 | 切换 Agent / 终端后，仅当前会话有 `.on` 与 `aria-current`；Tab + Enter 可切换；无当前会话时工作区标题可选中 |
| 右键菜单 | 工作区为「重命名工作区」，会话保留会话操作；合成行保留原有菜单 |
| 中英文、深浅主题 | 四种组合均检查；英文为 `Workspace · 2 sessions`；长标题截断，状态不被挤掉 |
| 完整桌面 App | 使用隔离接口样例检查真实导航；侧栏收起移除树，重新展开恢复工作区和子会话 |
| Android 真机组件 | Redmi Note 8（216d6a43），392 CSS px、DPR 2.75、coarse；10 行均至少 44px，无横向溢出；ADB 实际点按从 Agent 切到终端，始终只有一条选中 |
| Android 完整 App | LAN HTTPS 上硬刷新生产包；顶栏与四项底栏存在；ADB 点按项目、返回设置通过；ADB 滑动使内部列表 scrollTop 从 0 变为 339.64，顶栏和底栏保持可达，文档无横向溢出 |
| 边界 | 单会话合成、同名双会话、长标题、等待、休眠和互审均保留身份与状态；分组行省去重复时间，单会话与平铺会话仍显示时间 |

截图只上传到 PR 的 `pr-shots` 分支，不提交到主分支。组件样例是验收夹具，不是新增产品路由。手机上额外展示桌面树只用于验证粗指针；正式手机导航维持既有结构。

手机的 `roami chrome --cdp` 返回 `CHROME_BROWSER_IDENTITY_UNAVAILABLE`，因此通过该设备同一 ADB 转发连接 CDP，触控仍使用 `roami adb` 的实际点按和滑动。

## 自动检查

- `scripts/dev/quality/check.sh full`：通过，包含 Go 测试、typecheck、i18n、hover 和生产构建。
- 提交钩子执行 `scripts/dev/quality/check.sh quick`。
- `npx vitest run --maxWorkers=2 --minWorkers=1`：全部 186 个测试文件、1326 条测试通过；限制并发以免默认并发占用过多资源。
- `git diff --check`：通过。扫描 `frontend/src` 的图标符号，改动区域没有新增文字图标或 emoji。
- 本次没有 Python 改动，完整门禁按仓库范围规则跳过独立 Python 检查。

第一次 full 运行受父会话的 ROAMI/ROAM 环境别名与会话续接集成测试影响失败。清除测试进程继承的 ROAMI/ROAM/TTMUX/TMUX 变量后复跑通过，未为此修改业务代码。

本次仅改变呈现，不新增接口、轮询或请求；没有 CPU、内存或性能收益声明。
