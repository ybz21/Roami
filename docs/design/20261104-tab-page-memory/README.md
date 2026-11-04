# 工作区标签恢复当前页面

## Product Design

切换工作区标签、桌面导航或手机底栏时，恢复该入口最近访问的完整页面。页面内的返回、项目链接、深链继续导航到明确指定的位置。关闭标签清除该标签保存的地址。

OKR 项目额外保存「OKR 与看板 / 具体活动 / 文件」和看板内「OKR / 数据看板 / 当前状态」选择，返回项目时继续原来的视图。沿用现有布局、文案与交互，不增加按钮。

## User Stories

- 在 OKR 打开某个项目，切到首页再点 OKR，仍然进入同一项目。
- 在设置进入某个分类，切到其他标签再回来，仍然进入同一分类。
- 在 OKR 看数据看板或文件，离开后返回时保留视图选择。
- 主动返回列表后，下次切回仍在列表；关闭标签后重新打开，从入口开始。
- 不同机器的项目、设置地址与 OKR 视图互不覆盖。

## Technical Design

- `app/usePageTabs.ts` 接收完整路由，记录各一级入口最后访问的标准化路由。路由记录按节点存入 `localStorage`，只接受属于相应入口的路由。
- `selectPage` 仅供工作区标签、桌面导航、页面搜索和手机底栏恢复页面。`useAppRoute.go` 保持明确导航语义，避免返回列表被记忆地址劫持。
- `WorkspaceTerminals` 的页面标签和关闭后相邻标签选择复用恢复入口。会话、文件标签仍走既有任务导航。
- `projects/okr/okr-view.ts` 按节点和项目保存两级视图选择。只保存导航状态，不缓存数据或保留隐藏页面实例，不增加后台轮询。
- 页面 query 参数继续由既有 `go` 保留，页面记忆不覆盖节点参数。

## Acceptance

- `page-navigation.test.tsx` 覆盖切出切回、重新挂载、明确返回列表、关闭标签、相邻标签恢复、任务入口、节点隔离和无效存储。
- `ProjectOkr.test.tsx` 覆盖桌面与手机下的项目视图恢复，以及不同项目互不覆盖。
- 前端全量：187 个测试文件、1,333 条测试通过；typecheck、i18n、hover 审计与生产构建通过。
- 仓库 quick、PR 前 full 检查通过。首次运行受到会话注入的旧环境变量影响，`TestBridgeEnvAliases` 失败；仅对检查进程移除 `ROAM_HOME` 与 `ROAMI_WEB_PASSWORD` 后通过。
- 浏览器与真机交互验收记录见下方，截图为 `/tmp` 中的交付产物，不加入主干。

### 浏览器与 Android 真机

独立实例：`scripts/dev/isolated-roami.sh /tmp/roami-tab-memory-test ...`，HTTPS `:23641`；项目及 OKR 为专用测试数据。

- 桌面真实点击：项目「数据看板」切到首页再切回 OKR，仍为 `okr/2026-1104-2200-wntm` 和「数据看板」；设置「快捷键」切到 OKR 再回来，仍为 `settings/ui/keys`。
- 桌面 1280、1920、2560、3440 CSS px：没有文档横向溢出，工作区内容高度分别为 835 / 1015 / 1015 / 1015 CSS px（1280 档视口高 900，其余高 1080）。本次没有修改布局或新增可选面板。
- Redmi Note 8，392 CSS px，coarse 指针：ADB 点按数据看板、首页、项目，恢复为 `projects/2026-1104-2200-wntm/okr` 和「数据看板」。捕获 `pointerdown` 确认原生点按确实到达相应控件。
- ADB 上滑后内容滚动位置从 0 到 321.45 CSS px；顶栏、底栏可见，无文档横向溢出。
- 手机初始被系统 NotificationShade 持有焦点，CDP 触摸唤回 Chrome 后恢复 ADB 点按；后续通过真实 ADB 操作验收。`roami chrome --cdp` 无法识别手机浏览器身份，因此手机页面断言使用已有 ADB 转发上的原生 CDP。
- 中文、英文页面均保留项目和 Dashboard 选择。截图：`/tmp/tab-page-after-desktop.png`、`/tmp/tab-page-after-phone.png`。

PR 对照截图使用同一独立实例的测试项目：修改前代码打开项目后切到首页再切回 OKR，地址退回 `okr` 列表；修改后保留项目地址与数据看板。截图经 `scripts/dev/pr-shot.sh` 上传到 `pr-shots`，不提交主干。
