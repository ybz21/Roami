# 本轮检查与后续验收

2026-11-03 · **设计与概念稿检查，不是产品功能验收。**

[返回方案](README.md)

## 本轮产物

- 产品方案、用户故事、视觉与动画语义：`README.md`。
- 技术架构、数据所有权、Main 回流、依赖门禁、接口、代码拆分与迁移：`technical-design.md`。
- 可编辑概念稿：`index.html`、`assets/studio.css`、`assets/studio.js`。使用演示数据，不发任务、不调用模型、不连接生产蜂群。
- 单文件离线预览：`/tmp/swarm-main-three/index.html`。将相同源码中的固定 Three.js 模块下载到临时目录，用已有 esbuild 打包并内联 CSS / JS；外部资源请求数为 0，未增加项目依赖。Three.js MIT 许可随预览保留。
- 截图：`/tmp/swarm-design-desktop.png`、`/tmp/swarm-design-light.png`、`/tmp/swarm-design-phone.png`、`/tmp/swarm-design-phone-detail.png`。
- 演示录屏：`/tmp/swarm-design-demo.mp4`。这些一次性媒体不提交进主分支。

## 已检查

| 检查 | 结果与边界 |
| --- | --- |
| 源码对照 | 核对 legacy swarm new/adopt、成员软依赖、终端推测状态、Web 请求和既有 Tasks / Dispatcher / 常驻执行器机制；方案中新增接口明确标为提案 |
| JS 与文档 | `node --check assets/studio.js`、`git diff --check`、本主题相对链接检查；无产品源码变更，不运行无关运行时全量门禁 |
| 桌面场景 | Chrome 中 `data-scene=ready`，帧序号增长；切换派发、执行、待验收、已验收，DOM 状态与场景同步 |
| 验收语义 | 待验收显示主 Agent“验收中”、成员“待验收”；只有手动切到演示“已验收”才显示完成；实际验证机制尚待实施 |
| 动画暂停 | 关闭动画后帧序号在采样期间保持不变；已验收终态也不继续绘制。未据此声称生产 CPU / 电量下降 |
| 主题和选择 | 桌面深浅主题切换、成员列表选择与工位选中联动；手机真实点按主题按钮可切换，所选成员保持 |
| 真机 | Redmi Note 8，ADB 序列号 `216d6a43`，物理 1080×2340、CSS 宽 392；经 LAN 打开隔离启动的静态设计稿 |
| 触控与滚动 | 使用 `roami adb ... input tap/swipe` 实际切换“待验收”、选择成员、滚动内容；`.scroll.scrollTop` 从 0 增长超过 500，文档 `scrollTop=0` |
| 手机溢出 | `scrollWidth=clientWidth=392`；body scrollHeight 与 clientHeight 同为 766；阶段按钮高度 44 CSS px；精简为只显示选中工位标签，避免遮住角色 |
| 依赖失败 | 手机初次访问 CDN 失败时场景给出降级提示，成员 DOM 列表仍能使用；改用离线预览后 `data-scene=ready`，没有 CDN 资源请求 |
| WebGL 失效 | 桌面使用 `WEBGL_lose_context` 实际触发 context loss 后显示暂停提示，仍可点成员列表选中“前端”；自动恢复与正式资源泄漏检查留待产品实施 |

浏览器操作优先使用 `roami chrome`。本机 Android CDP 的该 CLI 返回 `CHROME_BROWSER_IDENTITY_UNAVAILABLE`，因此手机 DOM 诊断使用同一 ADB 转发连接的 CDP；实际触摸仍用 Roami ADB，未用 DOM click 代替触控验收。

预览中的移动布局是独立概念页面，没有产品顶部 / 底部导航、任务数据或真实输入框。本轮只证明该概念稿在真机上可运行可触控；正式接入后必须重新验证产品上下栏、安全区、输入、路由与任务详情。

## 正式实施必须补齐

- 受管任务闭环：Main 原对话发起；Codex / Claude / Roami 实际执行、回报、独立验收与续改。
- 计划与依赖：并发幂等、环检测、版本失效、两个上游同时解锁、旧回报、断线、重启与 unknown 不重投。
- 生命周期：暂停只停派发；停止取得证据；归档不杀会话；关闭复用现有清理并保护未提交、未合入和非独占资源。
- 旧蜂群：保持身份与资源；显式接管；旧 done 不升级为 verified；新旧 engine 的 CLI / Web 写入入口一致。
- 性能：同机生产构建改前改后测请求、主线程、帧时长、draw calls、内存和前后台行为；1/8/24 与聚合规模。当前 60/30fps 仅目标，不是实测通过结论。
- Three.js：真实事件驱动、相机聚焦、验收短动效、系统减少动画偏好、context loss / restore、重复进入退出的资源释放和离线依赖。
- 产品前端：按仓库全量前端门禁、四档布局、深浅主题、中英文、键盘可访问性及 Android 实际触控验收。当前开发文档使用中文属于 i18n 规范例外。

所有测试静态服务经 `scripts/dev/isolated-roami.sh /tmp/swarm-main-three-preview ...` 启动；完成后停止本任务服务器，隔离 tmux 仅通过同一入口 `--stop` 清理。未启动真实蜂群或更改用户现有成员。
