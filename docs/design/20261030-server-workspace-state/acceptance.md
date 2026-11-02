# 验收记录

日期：2026-10-30。分支：`fix/server-workspace-state`。

## 隔离环境

通过 `scripts/dev/isolated-roami.sh /tmp/roami-workspace-instance ...` 启动私有 tmux 与 HTTPS 服务，端口 18379；使用独立数据、配置及会话。测试只创建 workspace-alpha、workspace-beta、workspace-gamma，不操作用户会话。Agent 运行时复用本机已安装依赖，不调用模型、不修改模型路由。

桌面通过 `roami chrome` 操作独立标签。手机为 Redmi Note 8（216d6a43），通过局域网 HTTPS 访问。当前 `roami chrome --cdp` 不接受 Android 的 `/devtools/browser` 端点，返回 `CHROME_BROWSER_IDENTITY_UNAVAILABLE`；使用同一手机 CDP 读取状态，真实触控由 `roami adb` 完成。

## 自动检查

- `scripts/dev/quality/check.sh quick` 通过，包含全部 Go 测试、格式检查、前端类型/i18n/hover 检查与敏感信息扫描。按范围跳过 Python 检查。
- 前端完整 Vitest：150 个文件、1107 条用例通过；后续身份引用稳定与节点隔离保护的定向回归通过。
- `go test -race ./backend/api -run TestWorkspace -count=1` 通过：并发增量、持久化重读、首次导入、关闭全部后不复活、文件选择清理、损坏文件不覆盖。
- `npm run typecheck`、`npm run i18n:check`、`npm run hover:check` 与生产构建通过。沿用既有大 chunk 提示，无构建失败。
- 运行全目录图标符号搜索，并核对变更行；没有新增文字图标或 emoji。

## 功能证据

- 旧版生产构建打开 alpha、beta，地址带 `terms`/`active`，会话列表存于 `roam.terms`。新版硬刷新后导入后台，地址成为 `#/w`，该节点的本地副本删除。
- 手机使用同一测试后台、独立浏览器存储；打开会话不会删除桌面其他标签。
- ADB 在手机切换到 beta；后台 active 更新为 beta，桌面在自动同步后选中 beta。
- 桌面点击 beta 标签关闭；后台与手机恢复 alpha，tmux beta 会话仍存在。
- 两个并发 PATCH 分别打开 beta、gamma；后台 revision 5，列表完整保留 alpha、beta、gamma。
- 随后打开只携带 alpha 的旧链接，后台仍保留三个会话并选中 gamma；地址清理为 `#/w?memoryView=activity`。
- 新版手机切换器展示共享“已打开”列表；通过 ADB 选择 alpha 后，后台保留三个标签且 active 为 alpha，当前终端只挂载一个。
- 真机通过底栏进入首页、项目、工具、设置，顶栏标题随路由更新；各页无横向溢出，底栏中心命中对应按钮。手机顶栏约 60.7 CSS px，底栏内容及安全区约 84.7 CSS px；会话覆盖层正确覆盖底栏，返回后恢复导航。
- 自动化覆盖远端关闭最后一个标签时收起手机覆盖层、断线保留本地操作并重试、相同快照保留引用、节点切换保留页面筛选且不携带会话列表。

截图为本次临时验收产物，不提交进主分支：

- 桌面改前：`/tmp/roami-workspace-desktop-before.png`
- 桌面改后：`/tmp/roami-workspace-desktop-after.png`
- 手机改前：`/tmp/roami-workspace-phone-before.png`
- 手机改后：`/tmp/roami-workspace-phone-after.png`

## 刷新预算

对比 HEAD 与修改后的生产构建。旧版没有工作区读取；新版在一次 18.839 秒采样里记录 5 次 `/workspace` 请求，其中 1 次为验收手动读取，其余符合约 5 秒一次的轻量同步。移动切换器复用 `useSessionOverview`，不再单开轮询；手机仅在打开覆盖层时探测当前会话，身份表未变不重启终端请求。

其他请求的采样时长和交互不同，不比较总量；没有据此声称 CPU 或内存降低。隐藏暂停、前台恢复、请求合并与错误退避复用已有 `pollWhileVisible` 机制。

构建体积：HEAD 的 JavaScript 合计 23,245,247 B，修改后 23,248,864 B（+3,617 B）；全部 Brotli 旁路产物 5,426,944 B → 5,428,059 B（+1,115 B）。首次 HEAD 构建 44.58 秒，最终构建 44.69 秒；构建时长受同机负载影响，不作性能结论。

验收后已关闭本任务的桌面/手机浏览器标签，移除 tcp:19556 转发，停止测试 Web 服务，并通过同一个隔离入口执行 `--stop`；未清理用户的 tmux 服务。线上未部署。
