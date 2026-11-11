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


## 详情下载与榜单 API 修订

用户现场复现：运行节点能够读取 GitHub commit / tree，但对 `raw.githubusercontent.com` 的文件请求返回 `MARKET_UNAVAILABLE`，旧下载链路直接结束。使用同一节点环境验证修复版，两个文件均经 Git blob API 读取成功，保留原 commit，详情完整返回。

正式 v1 榜单、搜索、详情的匿名实测均为 401；当前节点未配置 OIDC。公开 JSON 三种榜单均返回 200，仓库型结果分别为 172 / 171 / 199 项，均有后续分页。正式 API 使用模拟授权响应验证身份头、完整文件与内容摘要；自定义镜像不接收节点令牌。

新增回归覆盖：GitHub tree 限流、raw 文件失败、固定 commit 归档、精确 blob 读取、正式 API 快照、授权失效不注销 Roami、单次 HTTP 详情请求携带完整内容与安装回执、三种榜单切换、失败后保留原榜单与搜索草稿。

本次前端全量 Vitest 为 227 个文件、1,636 项通过；`GOFLAGS=-p=1` 下的 full 门禁通过，相关 Python 回归 95 项通过。未配置 OIDC 的真实公开接口，三种榜单、一次详情请求、展开完整正文、安装到隔离 Roami 节点均通过独立 Chromium 验收。桌面四种宽度、侧栏开关、英文模式均通过。

## 面向用途的详情展示修订

参考 [skills.sh 的 find-skills 页面](https://skills.sh/vercel-labs/skills/find-skills)，将窄弹窗中的原始文本改为能力中心内的阅读工作区。用途摘要来自技能原始元数据，场景、示例、表格、代码及效果图沿用发布者内容，不补造效果数据；这些外部文件内容保留原文。文件页能查看完整原始指令、引用文件、脚本及许可证，包内文档链接可切换到对应文件。

- 前端全量 Vitest：228 个文件、1,640 项通过。新增覆盖折行元数据、UTF-8 与二进制识别、默认功能文档、效果图片、包内引用、原始文件切换及不执行 HTML。
- 独立 Chromium 使用真实公开列表与固定版本内容，验证用途摘要、完整排版、SKILL.md / LICENSE 切换、保留列表返回、仅 Roami 安装及英文浅色模式。1280 / 1920 / 2560 / 3440 CSS px 下，侧栏打开和关闭均无文档横向 / 纵向溢出，阅读区可用高度约 906px。
- Android Redmi Note 8（392 CSS px、coarse）经 ADB 实际点按打开详情、展开安装位置、取消本机 / Claude / OpenCode、切换文件并选择 LICENSE、点按底部安装。隔离节点记录的 commit 为 `e781cb4d07433dfe1d19e924ed45cc61738c55ec`，保留 SKILL.md 与 LICENSE。滑动使详情 scrollTop 从 0 增至 288，底部按钮保持可见且命中，文档无横向溢出。
- 所有安装测试仅写入 `/tmp/roami-skills-rich` 的隔离 Roami 节点；未向用户本机 Agent 目录安装测试技能。

截图：`/tmp/skills-rich-desktop.png`、`/tmp/skills-rich-examples-desktop.png`、`/tmp/skills-rich-files-desktop.png`、`/tmp/skills-rich-phone.png`、`/tmp/skills-rich-files-phone.png`、`/tmp/skills-rich-light-en.png`。手机 PR 截图仅包含网页内容。

## 官方榜单标签、安装引导与效果图片

依据用户提供的两张官方截图修订：累计 / 24 小时趋势 / 热门使用下划线标签，数量直接来自 JSON 榜单的 total 或正式 API 的 pagination.total。公开接口的榜单窗口计数与官网全站技能总量不同，界面不以已加载数量、搜索命中数或截图中的 1,328,493 作为总数。未知、异常和零数量隐藏，切换失败保留已成功榜单及选中状态。

详情新增命令 / 给 Agent 的提示词切换及复制，明确命令执行电脑与一键安装当前节点的区别。手机将命令区及安装来源收起，优先展示效果图与正文，保留固定底部安装按钮。官方 URL 和完整技能标识可直接提交打开详情，返回保留原草稿及列表。

实际使用 `designed-by-ai/skills/design-mobile-apps` 验收。该技能说明引用的 GitHub raw 图片直连失败；节点经 GitHub Contents API 读取后，以选项级预览图片返回，浏览器成功解码为 1586 × 678。图片不进入安装文件，仅允许公开 GitHub 的已验证位图，最多三张、单张 384KB、总计 768KB，额外加载整体最多六秒。失败或不支持的图片不阻断正文；拒绝路径穿越、伪造域名、查询凭据、SVG / HTML 及过大内容。

full 门禁通过：Go、Python lint / format、相关 Python 113 项、前端审计 / 类型检查及构建、secret scan。前端全量 Vitest 为 228 个文件、1,643 项通过。后续仅调整手机来源折叠与标签触控宽度，并重新执行前端全量测试及生产构建。

最终 Android 通过 ADB 实际输入官方 URL、切换三个榜单、展开命令区、切换到提示词并分别复制成功、打开文件页选择 designing.md（7,851 字符），再取消本机 / Claude / OpenCode，仅安装到隔离 Roami 节点。持久记录固定 commit 为 `03c20aec6dcedb5fabfb03dc37982eb52ef19ed6`，保留八个原始文件，不包含预览图片。手机首屏效果图边界为 y=510.65…664.86，固定安装栏从 y=673.09 开始，整张图可见；累计标签实际宽度 44px，文件菜单选项高度 44px。

最终前端全量测试仍为 1,643 项通过，类型检查 / i18n / hover / 生产构建通过，quick 与 full 门禁通过。截图为 `/tmp/skills-official-rankings-all-desktop.png`、`/tmp/skills-official-detail-desktop.png`、`/tmp/skills-official-rankings-phone.png`、`/tmp/skills-official-detail-phone.png`、`/tmp/skills-official-guide-phone.png`，通过 pr-shots 发布。

## 移除重复 Installation 区域

按用户修订，删除详情中的命令 / 提示词安装区，包括手机折叠入口及对应组件、样式、翻译和已失效的复制测试。正文直接呈现功能文档及效果图；桌面只使用右侧安装栏，手机只使用底部安装按钮。此前的安装引导验收为历史记录，不代表当前界面。

本次前端全量 228 个文件、1,642 项测试通过；typecheck、i18n / hover、生产构建及按提交 7449b843 对比的 full 门禁通过。仅修改前端与文档，按规则跳过无改动的 Python / Go。桌面 1280 / 1920 / 2560 / 3440 CSS px、侧栏开关均无溢出，只有右侧一个安装入口，实际安装到隔离 Roami 节点成功。Android 真机 ADB 打开详情与安装位置；确认无命令区、仅一个底部安装按钮且命中正确，效果图完整解码（1586px），图底 y=592.13，底栏顶 y=673.09，无横向溢出。

改后截图：`/tmp/skills-single-install-desktop.png`、`/tmp/skills-single-install-phone.png`。
