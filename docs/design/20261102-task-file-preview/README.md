# 任务结果文件预览

## 产品设计

任务详情负责展示结果和交付文件，文件正文进入独立阅读空间。
文件行以类型图标、文件名、大小和日期呈现身份；预览使用蓝色图标文字按钮，下载保留次级层级。
手机上的操作另起一行，长文件名可以换行，触控区域至少 44px。

桌面预览在新浏览器标签打开，有可刷新的独立地址；页头只保留返回、文件名和下载，正文铺满剩余空间。
手机预览沿用全屏二级页，单层返回栏、右侧下载、单一正文滚动区域；不把文档塞入任务列表或弹窗。
HTML 保留文件本身的视觉与沙箱限制，Markdown 使用阅读宽度，PDF、PPTX 和图片沿用现有查看器。
超过预览限制或不支持的格式仍可下载。

## 用户故事

- 从任务详情打开 HTML 报告或 Markdown 后，获得完整阅读区域。
- 桌面关闭新标签即可回到原任务，手机返回保留任务选择、草稿与滚动位置。
- 从原生会话的文件分组进入相同的阅读流程。
- 新页刷新、切换其他节点后，仍从文件所属节点请求元数据与正文。
- 文件不可用时，保留返回入口并允许重试。

## 技术设计

- `artifact-preview-route.ts` 生成 `#/artifact/:id`，保存来源节点与应用内返回地址；拒绝畸形编码并约束返回路径。
- `App` 在现有鉴权和节点引导后挂载独立 `ArtifactPreviewPage`，不挂载完整工作区；预览页自行订阅 `useLayout()`，确保直接访问时也初始化屏幕档位与触控规则。
- `ArtifactPreviewPage` 显式使用来源节点加载元数据、正文和下载；取消过期请求，不增加轮询。
- `TaskArtifactLink` 为桌面提供原生新标签链接，普通手机点击打开 `TaskArtifactMobilePreview`，修饰键点击保持浏览器行为。
- `AgentTasks` 和 `NativeSessionArtifacts` 共用入口；执行记录中的文件链接采用相同流程。
- `TaskArtifactPreview` 保留 HTML 沙箱和 CSP；`task-artifact-preview.css` 提供完整阅读空间，文件列表不再挂载正文。

## 验收

验收使用隔离服务和真实组件夹具；截图位于本机临时目录，不提交图片到主分支。

- 前端 `typecheck`、`i18n:check`、`hover:check`、Vitest、生产构建通过；161 个测试文件、1,187 项测试通过。
- 仓库 quick 门禁通过，未修改 Python，按范围规则跳过 Python 检查。执行时仅对门禁进程移除 `ROAM_HOME`：会话继承的该变量会影响既有 `TestBridgeEnvAliases`。
- 桌面真实点击预览链接打开独立标签，报告 iframe 高度 933px（视口高 993px），正文页不挂载任务工作区；硬刷新后仍可阅读。
- 桌面中文深色、英文浅色及长文件名均检查，无文档横向溢出。
- Redmi Note 8 通过 LAN HTTPS 验收，392 CSS px、DPR 2.75、compact/coarse。按钮视觉高 40px，命中区域至少 44px；真实 ADB 点击可打开全屏 HTML。
- 手机预览只有一条返回栏，iframe 高 681px（视口高 742px）；ADB 真实滑动可滚动报告，顶栏保持可用，没有横向溢出。
- ADB 顶栏返回和系统返回均关闭预览；英文长文件名场景返回后，草稿 `Keep this task draft` 保留，任务列表 scrollTop 保持 262.91px。
- HTML 沙箱和 CSP 回归测试通过；来源节点、刷新路由、错误重试和修饰键点击有专项测试。
- 补齐正文和图片加载失败后的原页重试；两项新增回归用例在旧实现失败、修复后通过。桌面和 Redmi Note 8 注入首次正文请求 503，点击重试后恢复 HTML，手机重试按钮命中区为 44px，任务草稿保持不变。
- 临时前端夹具、隔离服务及其 tmux 实例、测试浏览器页签和本任务的 ADB 转发均已清理。未更新用户当前运行的服务。

截图使用验收样例内容，不是对用户任务执行结果的重新验收：

[桌面改前](/api/file/tmp/task-file-preview-desktop-before.png) ·
[桌面文件列表改后](/api/file/tmp/task-file-preview-desktop-after.png) ·
[桌面独立预览页](/api/file/tmp/task-file-preview-desktop-reader.png) ·
[桌面英文浅色](/api/file/tmp/task-file-preview-desktop-light.png) ·
[手机改前](/api/file/tmp/task-file-preview-phone-before.png) ·
[手机文件列表改后](/api/file/tmp/task-file-preview-phone-after.png) ·
[手机全屏预览](/api/file/tmp/task-file-preview-phone-reader.png) ·
[手机真实滚动](/api/file/tmp/task-file-preview-phone-scrolled.png) ·
[手机英文长文件名](/api/file/tmp/task-file-preview-phone-long-reader.png)。

[桌面正文失败重试](/api/file/tmp/task-file-preview-desktop-retry.png) · [手机正文失败重试](/api/file/tmp/task-file-preview-phone-retry.png) · [手机重试后恢复](/api/file/tmp/task-file-preview-phone-recovered.png)。

合入前补充：独立页不经过 AppShell，增加直接访问时的 compact/coarse 初始化回归；用例在旧实现失败，修复后通过。Redmi Note 8 从独立地址冷启动实测 compact/coarse，返回和下载的命中区域均为 44px，无横向溢出。[手机直接访问](/api/file/tmp/task-file-preview-phone-direct.png)。
