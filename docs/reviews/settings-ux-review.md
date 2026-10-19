# Roami 设置：产品与交互评审

评审日期：2026-10-19。代码基线：`a6aec03`。本次只产出评审文档，不修改产品代码。

## 评审范围与证据边界

覆盖桌面 Web 设置、compact/移动 Web 设置，以及设置外实际存在的通知策略入口。桌面与移动端共用 `SettingsPage`、`registry` 和各设置组件；仓库中未发现另建的原生桌面设置页。Android App 的 `WebActivity.kt` 加载同一 Web 页面，本报告不把 Android 系统设置或服务器选择器算成设置分类。

本次以静态代码为主，复用 `/tmp/roami-settings-review/results.json` 及同目录已有截图，没有联网、没有新开浏览器、没有触发设置写入。原工作区检查时没有未提交变更，也没有已有报告可覆盖。既有截图中的环境标识包含 `review-fixture`，因此其中的写入、失败场景和尺寸数据作为评审场景证据，不等同于生产状态或真实设备验收；本次也没有重新确认其运行环境。下文将代码事实、既有记录和产品判断分开描述。

结论：共 **22 项问题：P0 0 项、P1 11 项、P2 11 项**。优先修复保存可信度、设置值编辑、读取失败状态和被裁切的内容，再调整分类与入口。没有证据支持将本次发现定为 P0，不据此推断不存在其他风险。

优先级口径：P0 为已确认造成严重、广泛阻断或数据损失且应立即处理的问题；P1 为设置无法可靠完成、状态误导、可能丢失编辑或重要操作防护不足；P2 为可发现性、命名、信息负担与一致性改进。跨维度问题只计一次。

## 一、现状清单

### 1. 分类、层级与页面

注册表有 **20 个页面定义，19 个在分类树可见**；`node.memory` 已注册、可搜索和直链访问，但没有加入分类树。页面数不是设置字段数：自定义组件内部还包含表单、动态列表和弹窗，不能将一个 `custom` 块计成一个设置字段。

| 当前导航位置 | 页面与路由（统一前缀 `#/settings/`） | 实际条目与子功能 | 默认值、适用范围与保存方式 |
| --- | --- | --- | --- |
| 跟着我走 / 常用 | `common` | 外观主题、语言、Claude 可执行文件、弹框提醒、推送通知、显示语音按钮 | 六个既有条目的快捷副本，显示来源文字；主题深色、语言中文、Claude 命令 `claude`、弹框提醒开、语音按钮开；推送读取当前浏览器订阅 |
| 跟着我走 / 界面 / 外观与语言 | `ui/look` | 深浅主题、Claude Code 主题跟随、账户操作（全屏、退出登录）、语言、信息密度 | 主题跟随默认开；密度宽松；主题/语言有浏览器本地权威值，服务端偏好作为备份和首次默认；其他偏好不能据此认定跨节点同步 |
| 跟着我走 / 界面 / 工作区布局 | `ui/layout` | 侧栏收成轨、终端区默认展开、方向簇、方向簇位置 | 分别默认开、开、开、右侧；前两项与桌面工作区有关，方向簇仅手机出现；开关/分段直接更新偏好 |
| 跟着我走 / 界面 / 快捷键 | `ui/keys` | 全局搜索、开任务、开终端、收起当前标签、开合右栏、终端聚焦/收起侧栏 | 从 `DEFAULT_KEYBINDINGS` 解析默认组合；录制即提交，可重置单项，显示冲突提示 |
| 跟着我走 / 界面 / 更多快捷键 | `ui/keys/more` | 搜文件内容、右栏切到文件、右栏切到 Git、语音输入 | 同上；按前六项/剩余项拆页，没有手机专用输入方式 |
| 跟着我走 / 界面 / 状态条 | `ui/status` | 总开关；系统来源 core、git、tasks；插件来源分组、内置/第三方标记与开关 | 总开关与系统项默认开；内置插件默认显示，第三方需要显式选择；偏好自动保存 |
| 跟着我走 / 智能体 / 模型与连接 | `agent/runtime` | 共享 Base URL/API Key；Main、Worker 模型与推理强度；高级上下文窗口、图片能力；测试连接/读取模型目录、保存、放弃修改 | 实际标为**本机**；模型由接口读取，不能把通用候选当成默认配置；空 API Key 表示保留；有加载、错误重试、未保存状态 |
| 跟着我走 / 智能体 / 统一记忆 | `agent/memory` | 知识/活动视图；个人、偏好、项目等范围；状态、搜索、分页、活动日期；查看来源、确认/拒绝、删除、彻底忘记 | 实际标为**本机**；内容与总量由接口返回；项目读取失败可重试；彻底忘记有确认弹窗 |
| 跟着我走 / 智能体 / 能力管理 | `agent/capabilities` | Skills、CLI、MCP、Tools 四个 Tab；目录搜索、可变能力启停、技能内容/引用文档、工具参数、MCP 连接详情；技能/工具导入说明弹窗 | 实际标为**本机**；启停等待服务端回执；内置固定项不能切换；导入按钮当前只打开“尚未激活”的说明，不执行导入；旧 `agent/skills` 等路径兼容映射到此页 |
| 跟着我走 / 智能体 / 专业智能体 | `agent/bin` | Claude Code、Codex、OpenCode、Pi 卡片；详情弹窗、高级可执行文件配置；安装探测/用量未知说明 | 可执行文件默认依次 `claude`、`codex`、`opencode`、`pi`；输入每次变化直接提交偏好，不同于常用页的失焦提交；卡片并不证明已安装或有可读用量 |
| 跟着我走 / 智能体 / 新会话 | `agent/new` | 快捷命令新增/移除、推送订阅与测试、弹框提醒、显示语音按钮 | 快捷命令默认空；此处混合会话入口与持续通知行为；偏好写入有 300ms 防抖，推送独立订阅 |
| 这台机器 / 浏览器 (Chrome) | `node/browser` | 自动/无头/有头模式、窗口尺寸、宿主机全屏、设备缩放、用户数据目录、Chrome 路径；页头重启 Chrome | 前端回退值：`auto`、`1920,1080`、全屏开、缩放 `2`、`/tmp/ttmux-chrome`、路径空；实际服务端配置可覆盖；输入失焦/Enter 写配置，开关即时写，重启是另一个请求 |
| 这台机器 / 手机 / Android | `node/phone` | **Android 和 iOS 两张卡**；平台开关与依赖安装、设备刷新与选择；Android 新建/启动/停止/删除 AVD、USB 重连/转无线、远程连接/断开；iOS 来源、手动地址、连接/启停/测试；日志 | 前端初始目标 Android/AVD，iOS 来源 simulator；实际以接口为准；配置自动保存，设备/镜像动作单独执行；状态和设备清单轮询 |
| 这台机器 / 语音输入 | `node/speech` | 不启用/OpenAI/Volcano Engine；OpenAI Base URL、API Key、模型、语言；火山 API Key、兼容 App ID/Access Token、Resource ID、Endpoint | 前端默认 provider 空；OpenAI 默认模型 `whisper-1`；**显式保存**，有保存中与成功/失败反馈；密钥保留语义应以服务端为准，不能从空输入认定已清空 |
| 这台机器 / 网络加速 | `node/p2p` | 实验性 P2P 总开关、STUN 增删/检测/优选/恢复跟随服务端、连接超时、候选收集上限、低速回退阈值 | 默认关、两个超时均 30 秒、阈值 200 KB/s；STUN 空偏好表示跟随服务端；这些控件写 `preferences`，STUN 文案明确为本浏览器定制，不能将本机徽标理解为统一节点配置 |
| 已注册、导航未列出 | `node/memory` | 单会话内存上限：自动、4G/8G/12G/16G、自定义、关闭护栏 | 默认读取全局环境变量 `ROAM_SESSION_MEM_MAX`，缺省选自动；预设即时提交，自定义需“设置”；是进程内存护栏，与智能体记忆不同 |
| 这台机器 / 环境变量 | `node/env` | 全局 KV 清单、新增（同名写入）、删除；页头“推送到会话” | 默认清单由接口读取；新增/删除有独立请求；删除需确认；新会话自动注入，既有会话需另推送 |
| 这台机器 / 安全 | `sec` | 修改登录口令、TOTP 状态/开启/查看当前二维码/关闭、证书下载与安装说明 | 改密需旧口令、新口令至少 6 位、二次确认；TOTP 开启需校验 6 位码，关闭有 Popconfirm；状态来自接口，不存在统一可假定的初始开关值；证书实际下载 `/cert.crt` |
| 整个集群 / 多机 | `cluster` | 当前节点/中心角色；接入中心地址、一次性令牌、节点名、组、跳过证书校验；加入/退出；中心公开地址与令牌时效；中心自身卡；访问地址、保存与重启 | 配置来自当前节点，必要时另读中心自身配置；表单显式保存；切中心与退出已有确认；部分修改需重启。不是单一集群全局配置表 |
| 分类树末尾（接在整个集群段后） | `about` | Logo、版本、检查更新、发布页/仓库链接、PWA 安装或已安装状态、证书下载、平台说明、进入安装页 | 页面标为“跟着我走”，版本由服务端返回；更新检查有失败降级入口；本次没有执行检查更新或访问外链 |

以上页面来自 [注册表](../../frontend/src/components/settings/registry.tsx)，基础默认值来自 [preferences.ts](../../frontend/src/preferences.ts)。字段默认值只描述代码初始化/回退，不能代替实际部署值。

### 2. 设置页之外的现有入口

| 入口 | 实际内容 | 保存与边界 |
| --- | --- | --- |
| 手机设置首页“应用与设备” | 下载 App / 装到主屏、安装说明、手动全屏（隐藏系统栏） | 是 compact 专属入口，不是注册表中的另一套设置页；`onInstall` 进入安装路由 |
| 通知铃铛 / 通知弹窗 / 设置 Tab | 任务结果、决策、提醒、建议四类通知；时区；免打扰时段；需关注通知是否绕过免打扰；隐藏预览；每小时建议上限 | `AgentNotificationSettings` 独立 GET/PUT；显式保存、有失败重试；默认任务结果/决策/提醒开、建议关、免打扰关、绕过关、隐藏预览开、建议上限 1；打开免打扰时填入 22:00–08:00；时区来自运行时默认参数，类缺省为 UTC |
| 终端工具栏 | 弹框提醒快捷切换；快捷命令和语音入口是对应设置的使用位置 | 现有说明有提到工具栏入口；不将使用按钮重复计成设置字段 |
| JSON | 展示当前 `getPreferences()` 的只读 JSON | 桌面页头、手机分类末尾入口；不是导入/导出/恢复，也不包含所有独立配置表单 |

通知实现见 [通知弹窗](../../frontend/src/components/agent/AgentNotifications.tsx)、[通知设置](../../frontend/src/components/agent/AgentNotificationSettings.tsx)、[策略默认值](../../agent-runtime/src/roami_agent/replies/notification_policy.py)。安装路由与通知入口见 [App.tsx](../../frontend/src/App.tsx)；Android 容器见 [WebActivity.kt](../../mobile/android/app/src/main/java/com/roami/app/WebActivity.kt)。

当前没有在此清单中发现“恢复全部默认设置”“删除账户”的统一入口，不将其假定为已有功能或必需补齐的功能。已存在的重置主要是快捷键单项重置和 STUN 恢复跟随服务端。

### 3. 已有界面记录与值得保留的行为

- 分类支持独立 URL；桌面分类树和手机列表由同一注册表生成。移动子页使用 `MobileSubPage`，`manageHistory={false}`，保留底部四项导航；不会因有 URL 又主动压入一份覆盖层历史。
- 既有 `mobile:node/p2p`、`mobile:node/phone`、`mobile:ui/look` 记录均为 compact/coarse，`overflow=0`、`wide=[]`。已查看外观页截图：子页标题只显示一次，底部仍有首页、项目、工具、设置。记录中的底栏命中结果为真实按钮，子页底部预留约 60px；这不足以证明全部触控区、安全区、软键盘和返回路径已完成真机验收。
- 退出登录已有危险色确认；改密校验旧口令与重复输入；TOTP 开启验证动态码；环境变量删除、AVD 删除、切中心和退出中心均有确认。AVD 删除说明包含应用和数据一起删除，应该保留。
- 模型配置已有加载、读取错误重试、密钥保留提示、未保存状态和放弃按钮；能力启停等待服务端回执；网络加速默认关闭且标实验性；STUN 区分参考/实测并提供恢复跟随入口；更新失败仍能进入发布页。后续统一体验时应复用这些已有模式。

## 二、发现的问题与改进建议

### A. 分类合理性（6 项）

#### SET-10 · P2 · 导航按作用域分段，实际写入目标却不一致

**现状与影响：** “模型与连接 / 统一记忆 / 能力管理”列在“跟着我走”之下，页头却标本机；“网络加速”列在这台机器下，内部又说明 STUN 是本浏览器定制；“多机”既管理当前节点也管理中心自身。关于页接在“整个集群”段后却标跟着我走。用户难以预判修改影响谁，换机器时也容易错误期待配置同步。

**建议：** 导航优先按任务领域组织，作用域作为独立徽标，明确区分“此浏览器 / 当前节点名称 / 中心名称”；混合作用域在字段组上标注，不只给整页一个徽标。保留节点名称反馈。

**涉及：** [registry.tsx](../../frontend/src/components/settings/registry.tsx) 199–202、311–315、370–380 行；[SettingsPage.tsx](../../frontend/src/components/settings/SettingsPage.tsx) 的 `PaneHead`；[preferences.ts](../../frontend/src/preferences.ts)；[ClusterSettings.tsx](../../frontend/src/components/cluster/ClusterSettings.tsx)。

#### SET-11 · P2 · 账户操作藏在“外观与语言”，且与全屏混为一组

**现状与影响：** 安全页没有账户操作，“退出登录”需要找到外观与语言内的账户块。全屏同时在手机“应用与设备”和账户块中出现。账户说明仍是“全屏与退出登录。关于与主题在同一页。”，不能准确说明当前页面关系。已有退出确认值得保留，问题在入口与文案。

**建议：** 将退出放入清晰的“账户与安全”区域或设置首页账户行；全屏放显示/应用与设备，保留一个主要入口；更新说明文字。不要把节点登录口令包装成不存在的个人账户资料。

**涉及：** [registry.tsx](../../frontend/src/components/settings/registry.tsx) 的 `accountItem`、`ui.look`、`sec`；[account-actions.tsx](../../frontend/src/components/settings/account-actions.tsx)；[SettingsPage.tsx](../../frontend/src/components/settings/SettingsPage.tsx) compact 分支；[中文文案](../../frontend/src/i18n/locales/zh-CN.ts)。

#### SET-12 · P2 · 通知设置分散，统一设置里找不到已有的免打扰策略

**现状与影响：** 推送订阅和弹框提醒放在“新会话”与“常用”；四类通知、免打扰、隐藏预览等实际在“铃铛 / 设置”Tab。它们不是缺失功能，但设置页没有交叉入口，搜索索引也未覆盖。既有搜索“免打扰”无结果。桌面通常需通知铃铛后再切设置 Tab，手机用户也需离开当前设置上下文。

**建议：** 增加“通知”设置入口，复用现有策略组件或直达弹窗 Tab，同时收纳设备订阅和弹框偏好。标明“通知发送策略”与“这台浏览器的接收权限”，避免将不同开关误认为重复。

**涉及：** [registry.tsx](../../frontend/src/components/settings/registry.tsx) 的 `agent.new`；[push-settings.tsx](../../frontend/src/components/settings/push-settings.tsx)；[AgentNotifications.tsx](../../frontend/src/components/agent/AgentNotifications.tsx)；[AgentNotificationSettings.tsx](../../frontend/src/components/agent/AgentNotificationSettings.tsx)。

#### SET-13 · P2 · 会话内存护栏未列入导航

**现状与影响：** `node.memory` 存在于 `pages` 和 `order`，但不在 `nodes`。既有搜索“内存”可以命中会话内存和状态条，分类列表却没有此页；只浏览分类的用户无法发现。“统一记忆”和“会话内存”也需要明确区分语义。

**建议：** 将该页加入本机高级/资源控制入口，命名为“会话内存限制”，保留“统一记忆”的知识含义。若确实需要隐藏，必须定义并实现平台/能力条件，不能留下无说明的孤页。

**涉及：** [registry.tsx](../../frontend/src/components/settings/registry.tsx) 317–325、370–380 行；[memory-settings.tsx](../../frontend/src/components/settings/memory-settings.tsx)。

#### SET-15 · P2 · 快捷键按数量拆页，手机仍只能录实体键盘组合

**现状与影响：** 两页由 `slice(0, 6)` / `slice(6)` 决定，名称“更多快捷键”不传达任务边界。手机分类列表同样展示两页，录制依赖全局 `keydown`，只提供按组合键、Esc 取消；没有触控录入或明确的取消按钮。未连接实体键盘的用户难以完成和退出录制。

**建议：** 快捷键合为一个可滚动、可按任务分组的页面；手机标注需要实体键盘，录制时提供可点取消，或提供修饰键选择输入。单项重置是低风险操作，可维持一击重置并补撤销反馈。

**涉及：** [registry.tsx](../../frontend/src/components/settings/registry.tsx) 254–260 行；[hotkey-recorder.tsx](../../frontend/src/components/settings/hotkey-recorder.tsx)；[SettingsPage.tsx](../../frontend/src/components/settings/SettingsPage.tsx) 手机列表。

#### SET-21 · P2 · 主题跟随默认开启，但影响的是另一款工具的本机配置

**现状与影响：** `claudeThemeSync` 默认 `true`；常用页只有 Roami 主题开关，没有展示跟随项。跟随说明位于外观页，明确会写 `~/.claude/settings.json`，且已打开的 Claude 还需要 `/theme` 或重开。用户从常用页切主题，难以预见这一额外影响。报告没有验证每种 Claude 运行状态下的应用结果。

**建议：** 常用页主题旁显示“同时同步 Claude”状态和直达入口；首次启用解释影响与生效时间，再由用户选择。保留单独关闭同步的能力。

**涉及：** [preferences.ts](../../frontend/src/preferences.ts) 84–99 行；[registry.tsx](../../frontend/src/components/settings/registry.tsx) 的 `claudeThemeItem`、`common`、`ui.look`。

### B. 展示合理性（6 项）

#### SET-03 · P1 · 读取失败被呈现成默认值、空列表或“未开启”

**现状与影响：** 环境变量读取失败被吞掉，仍显示“无环境变量”；多机初始失败时 `cfg=null` 返回空白；Chrome、语音、手机平台等读取失败保留初始化值；TOTP 状态请求失败直接 `setEnabled(false)`，呈现“未开启”和开启按钮。用户无法区分未配置和未读到，并可能在错误基线上继续写配置。既有 `readFailure:node/env`、`readFailure:cluster`、`readFailure:sec` 记录与这些分支一致；不能因此断言当时真实配置是什么。

**建议：** 每个读取流程区分加载/成功空值/失败；失败保留已知数据并给重试，未知时禁用依赖旧配置的写操作。TOTP 必须保留“状态未知”，不能报“未开启”。复用模型配置已有的错误重试模式。

**涉及：** [env-vars.tsx](../../frontend/src/components/settings/env-vars.tsx) 的 `load`；[ClusterSettings.tsx](../../frontend/src/components/cluster/ClusterSettings.tsx) 142–155 行；[security-settings.tsx](../../frontend/src/components/settings/security-settings.tsx) 的 `refresh`；[browser-settings.tsx](../../frontend/src/components/settings/browser-settings.tsx)、[speech-settings.tsx](../../frontend/src/components/settings/speech-settings.tsx)、[phone-settings.tsx](../../frontend/src/components/settings/phone-settings.tsx)、[status-bar-settings.tsx](../../frontend/src/components/settings/status-bar-settings.tsx) 的初始读取。

#### SET-04 · P1 · 桌面纯设置行页在低高度窗口被裁切

**现状与影响：** 桌面仅有自定义块的页加 `scroll`；纯开关/分段页的 `.rows` 为 `overflow:hidden`。既有“工作区布局”记录显示可用高度 192px、内容高度 263px，方向簇位置落在可视范围外；`desktop-short-layout.png` 也显示末项不可见。条数不超过六项并不能保证缩放、短窗口和翻译后的可达性。

**建议：** 所有设置页统一使用一个内容滚动容器，页头固定；不要以固定行数替代高度适配。回归短窗口、文字放大和键盘焦点滚入视野。

**涉及：** [SettingsPage.tsx](../../frontend/src/components/settings/SettingsPage.tsx) 295–301 行；[index.css](../../frontend/src/index.css) 3361–3371 行。证据：`results.json.smallHeight`。

#### SET-14 · P2 · 搜索没有覆盖自定义组件内部的真实字段和操作

**现状与影响：** `itemText` 只索引注册项的 label/desc/key/keywords/页面名，不深入自定义组件。专业智能体外层 keywords 没有 `codexCommand`；TOTP 只登记“两步”等词，没有完整操作“关闭两步验证”。既有这两次搜索均无结果，而 `workspace.density` 可以命中。搜索提示“名称、说明、键名都能搜”因此只对部分字段成立；常用副本还会重复计入命中总数。

**建议：** 给自定义块建立子字段和操作索引，复用实际文案与配置键；搜到后定位到字段或展开详情，不只“打开这一页”。常用副本按同一设置身份去重计数。通知索引缺口同时见 SET-12。

**涉及：** [registry.tsx](../../frontend/src/components/settings/registry.tsx) 90–93、272–273、343–347 行；[SettingsPage.tsx](../../frontend/src/components/settings/SettingsPage.tsx) 128–130、175–197 行。

#### SET-16 · P2 · 实现术语占据默认说明，手机阅读负担偏高

**现状与影响：** 外观页使用“与窗口档正交”“行高和内边距各收一档”；设置行默认展示 `promptPopupOff` 等内部键；P2P 帮助包含 srflx、frp、ICE 与多段说明。既有手机外观/P2P 文本及截图能直接看到这些内容。负向键名还和正向开关含义相反。P2P/状态条用 `--fs-micro` 展示多行解释，也偏离仓库“仅眉标/角标允许小于 12px”的用途约束。

**建议：** 主说明描述结果，例如“紧凑模式在同一屏显示更多内容”；高级技术说明折叠，配置键保留可搜索并放到高级信息。正文和长说明使用至少 meta/body 级令牌；P2P 首屏优先展示启用状态与是否回退，其余参数放高级区域。

**涉及：** [SettingRow.tsx](../../frontend/src/components/settings/SettingRow.tsx)；[p2p-settings.tsx](../../frontend/src/components/settings/p2p-settings.tsx)；[stun-settings.tsx](../../frontend/src/components/settings/stun-settings.tsx)；[status-bar-settings.tsx](../../frontend/src/components/settings/status-bar-settings.tsx)；外观和网络相关 i18n 文案。

#### SET-19 · P2 · “导入技能/工具”按钮实际只能打开未开放说明

**现状与影响：** 能力页导入按钮外观像可执行操作，但弹窗只展示 reserved/notActive 文案、格式说明和 API 路径，没有选择来源或提交。用户需点击后才发现不能完成；这不是已实现导入流程的错误态。

**建议：** 在入口直接标“暂未开放”，或改为“查看导入说明”；保留说明入口但移除主操作的预期。待功能开放再提供可执行主按钮。

**涉及：** [agent-capabilities.tsx](../../frontend/src/components/settings/agent-capabilities.tsx) 的 toolbar 与 `importOpen` Modal。

#### SET-20 · P2 · CLI/MCP 筛选无命中时缺少对应空态

**现状与影响：** Skills/Tools 分支有 `!items.length` 文案；CLI/MCP 用各自 `.filter(...).map(...)`，却没有“筛选无结果”分支。MCP 的 `!catalog.mcp.length` 只覆盖目录本来为空，不能覆盖筛选后为空。列表消失后用户不易判断是没有能力、过滤过严还是加载故障。

**建议：** 各 Tab 都区分“目录为空”和“没有匹配项”；提供清除筛选，保留目录总量与错误提示。CLI 空目录也应有明确说明。

**涉及：** [agent-capabilities.tsx](../../frontend/src/components/settings/agent-capabilities.tsx) 的 CLI/MCP 渲染分支。

### C. 交互合理性（10 项）

#### SET-01 · P1 · 偏好写入失败被吞掉，快捷命令仍提示“设置已保存”

**现状与影响：** `savePreferences` 先更新内存并通知 UI，再在 300ms 后 PUT，失败 `.catch(() => {})`。快捷命令在调用 `setPrefs` 后立即成功 toast，没有等待服务端。既有 `failedPreferenceSave.toast` 为“设置已保存”，与代码一致。其他依赖同一偏好存储的开关也没有可见失败状态；刷新或换节点后可能丢失服务端未写入的值。

**建议：** 偏好存储暴露保存中/已保存/失败与重试状态；等待成功回执才提示“已保存”。允许本地预览，但失败时明确“仅在当前页面生效，尚未同步”，保存草稿而非静默丢弃。

**涉及：** [preferences.ts](../../frontend/src/preferences.ts) 224–234 行；[quick-commands.tsx](../../frontend/src/components/settings/quick-commands.tsx) 的 `save`。证据：`results.json.failedPreferenceSave`。

#### SET-02 · P1 · 专业智能体路径逐字 trim/回填，编辑过程会损坏输入

**现状与影响：** 专业智能体详情用受控 `Input`，每次 `onChange` 都调用注册表 setter；setter 对输入立刻 `trim()`，空串立刻回填默认命令。逐字输入带空格路径时，刚输入的尾空格会被删除；全选删除时又出现默认值。既有 `professionalCommand` 记录最终值为 `/opt/myx`，写入记录也展示了编辑过程；粘贴完整带内部空格的值和逐字输入并非同一路径，不应笼统说所有带空格路径都失败。常用页 Claude 路径使用失焦草稿，行为又不同。

**建议：** 专业智能体复用 `TextControl` 的本地草稿模式，失焦/Enter 校验并提交；允许中间态为空或带尾空格，提交时再规范化，并提示实际命令。

**涉及：** [professional-agents.tsx](../../frontend/src/components/settings/professional-agents.tsx)；[registry.tsx](../../frontend/src/components/settings/registry.tsx) 144–173 行；[SettingRow.tsx](../../frontend/src/components/settings/SettingRow.tsx) 的 `TextControl`。

#### SET-05 · P1 · 显式保存表单离开时缺少草稿保护

**现状与影响：** 模型配置有 dirty 状态和放弃按钮，但分类跳转 `go` 直接导航；语音、多机、通知策略也使用本地表单加保存按钮，没有对应离开拦截或草稿恢复。通知弹窗切 Tab/关闭会销毁子组件。用户已习惯其他设置即时保存，很容易切页后才发现这几页尚未保存。这里是从卸载路径判断的风险，未重新运行交互实验。

**建议：** 统一标记需要保存的表单；有脏数据时在路由离开、关闭弹窗和切 Tab 处提供“保存 / 放弃 / 留在此页”，或持久化可恢复草稿。保留即时设置与表单保存两种模式，但清楚标明边界。

**涉及：** [SettingsPage.tsx](../../frontend/src/components/settings/SettingsPage.tsx) 的 `go`；[agent-settings.tsx](../../frontend/src/components/settings/agent-settings.tsx)、[speech-settings.tsx](../../frontend/src/components/settings/speech-settings.tsx)、[ClusterSettings.tsx](../../frontend/src/components/cluster/ClusterSettings.tsx)、[AgentNotifications.tsx](../../frontend/src/components/agent/AgentNotifications.tsx)、[AgentNotificationSettings.tsx](../../frontend/src/components/agent/AgentNotificationSettings.tsx)。

#### SET-06 · P1 · Chrome 配置保存与重启没有等待关系

**现状与影响：** 输入失焦发出 PUT；页头重启独立 POST `/browser/relaunch`。点击重启会先引发失焦，但没有代码等待 PUT 完成，因此存在旧配置先被用于重启的竞态；保存失败也不阻止重启。已有帮助说明会断开当前镜像会话，但执行按钮没有单独确认或保存完成状态。竞态的具体发生概率未实测。

**建议：** 页头动作先提交当前草稿并等待成功，再重启；失败留在表单。将“已保存、待重启”作为可见状态，镜像活跃时确认断开影响，重启期间锁定重复操作。

**涉及：** [browser-settings.tsx](../../frontend/src/components/settings/browser-settings.tsx) 的 `persist/commit`；[SettingsPage.tsx](../../frontend/src/components/settings/SettingsPage.tsx) 111–115 行；[registry.tsx](../../frontend/src/components/settings/registry.tsx) 359–361 行。

#### SET-07 · P1 · 查看 TOTP 密钥与关闭两步验证缺少再次验证

**现状与影响：** 已登录用户可以直接 GET `/2fa/qr` 查看现有 secret/二维码，关闭时只需确认弹层再 POST `/2fa/disable`，请求不带口令或动态码。后端对应处理函数没有再次验证。接口处于已登录保护范围内，因此问题是敏感动作的二次认证不足，不是“未登录可读取”。

**建议：** 展示已有密钥、关闭或更换 TOTP 前要求当前口令或有效动态码，并在服务端校验；二维码可主动收起，敏感操作防重复提交。保留开启时的扫码验证流程。

**涉及：** [security-settings.tsx](../../frontend/src/components/settings/security-settings.tsx) 的 `showCurrent/disable`；[auth.go](../../backend/auth/auth.go) 321–330、369–375 行；[server.go](../../backend/server/server.go) 的受保护路由组。

#### SET-08 · P1 · 中心自身配置未检查 HTTP 状态，重启失败也缺少可信反馈

**现状与影响：** `HubSelfCard` 两处 `fetch` PUT 不检查 `response.ok` 就提示保存成功，HTTP 4xx/5xx 也会被当成成功；`restartPrompt` 吞掉重启请求错误，接着轮询 `/api/version`，任意 HTTP 响应都能触发 reload，30 秒超时则静默停掉。用户无法判断究竟是已保存待重启、重启未发出还是服务恢复失败。此项为代码分支确认，未对运行服务做故障注入。

**建议：** 复用可解析错误的 API 层或显式检查 HTTP 状态；保存、重启、恢复分别报告结果；重启请求失败立即给重试，恢复探测检查成功响应并显示超时后的下一步。不要以“请求返回了响应”代替完成。

**涉及：** [ClusterSettings.tsx](../../frontend/src/components/cluster/ClusterSettings.tsx) 52–76、179–193 行。

#### SET-09 · P1 · “推送到会话”影响全部活跃会话，入口未说明目标与无操作结果

**现状与影响：** 页头动作直接调用 `/env/push`；CLI `Push` 遍历所有活跃会话注入环境变量。前端不展示目标会话/变量范围，也不解析命令结果，统一提示已推送；没有活跃会话、没有变量时后端正常返回说明文字，前端仍成功提示。已有“补发 export，不重启会话”说明值得保留，但不足以说明全部目标。

**建议：** 按钮命名“推送到全部活跃会话”，执行前显示会话数量与变量键名，确认影响范围；回执展示成功/失败/跳过数量，空目标明确“没有可推送的会话”。不要展示密钥值。

**涉及：** [registry.tsx](../../frontend/src/components/settings/registry.tsx) 326–333 行；[SettingsPage.tsx](../../frontend/src/components/settings/SettingsPage.tsx) 116 行；[env.go](../../internal/cli/env/env.go) 139–155 行；[api.go](../../backend/api/api.go) 的 `EnvPush`。

#### SET-17 · P1 · 不支持 iOS 的主机仍展示可执行的平台开关

**现状与影响：** `sup=false` 只渲染“仅 macOS”，没有禁用 iOS Switch；`toggle` 也没有 supported 检查，未安装即进入 `/phone/install`。既有手机记录同时出现“未安装 / 仅 macOS / 打开开关以连接”，给出了不能完成的操作暗示。标题“手机 / Android”又未准确涵盖页内 iOS。

**建议：** 不支持时禁用操作，直接说明“此节点不支持，需要 macOS + Xcode + idb”；安装与连接分开标明，安装前展示依赖和影响。页面改名“手机设备”，清楚标注镜像发生在当前节点。

**涉及：** [phone-settings.tsx](../../frontend/src/components/settings/phone-settings.tsx) 50–64、125–160 行；[registry.tsx](../../frontend/src/components/settings/registry.tsx) 的 `node.phone`。

#### SET-18 · P2 · TOTP 密钥复制未等待剪贴板结果就报成功

**现状与影响：** `copy` 用可选调用 `navigator.clipboard?.writeText`，没有 await；即使 API 不存在或 Promise 被拒绝，仍提示“已复制”。同步 try/catch 也不能捕获异步拒绝。手机安装和证书问题恰好可能影响安全上下文，错误成功提示会直接误导备份密钥的动作。

**建议：** 检查能力、等待写入成功再 toast；失败提示可选中文本手动复制，保持密钥可见且可选择。使用项目已有剪贴板处理方式时也应保留失败反馈。

**涉及：** [security-settings.tsx](../../frontend/src/components/settings/security-settings.tsx) 的 `copy`。

#### SET-22 · P1 · 统一记忆的普通删除直接执行，没有确认或撤销

**现状与影响：** 活跃记忆的更多菜单中，“删除”直接走 `mutate('delete')`，执行 DELETE `?forgetSources=false`；“彻底忘记”才有确认。普通删除保留来源，不等于彻底擦除，但仍会改变记忆内容，当前入口没有确认或撤销反馈，容易误点后失去当前条目。未推断服务端存在或不存在其他恢复手段。

**建议：** 普通删除增加轻量确认或短时撤销，明确“删除此条记忆，保留来源”；彻底忘记继续使用强确认并说明范围。菜单危险操作使用一致的危险样式。

**涉及：** [AgentMemoryCard.tsx](../../frontend/src/components/agent/AgentMemoryCard.tsx) 的 actions 与 Dropdown；[AgentMemory.tsx](../../frontend/src/components/agent/AgentMemory.tsx) 83 行。

## 三、改进落地顺序与检查点

| 批次 | 优先级与关联项 | 推荐结果 | 建议检查方式（本次未执行产品修复验收） |
| --- | --- | --- | --- |
| 先恢复可信度 | P1：SET-01、02、03、04、08 | 保存回执真实、输入不中途变形、失败不冒充空态、所有字段可达 | 偏好 PUT 失败不能报成功；逐字输入路径和清空再输入；GET 故障保持未知并可重试；低高度桌面滚到最后一项；中心返回 500 必须显示失败 |
| 再补安全与编辑闭环 | P1：SET-05、06、07、09、17、22 | 草稿不丢、保存后再重启、敏感动作复核、批量操作知道目标、不支持的平台不可操作、删除可防误触 | 编辑后切分类/关闭通知弹窗；延迟 PUT 后点击重启；取消二次认证不泄露密钥；零会话推送不报已推送；非 macOS 无可用 iOS 操作；普通删除可取消或撤销 |
| 最后统一入口与表达 | P2：SET-10、11、12、13、14、15、16、18、19、20、21 | 作用域可预期、通知/账户易找到、搜索覆盖真实字段、高级说明不过载 | 从设置内找到免打扰和退出；分类可见会话内存；搜索 `codexCommand`/关闭两步验证有结果；手机可点取消录键；剪贴板失败不报成功；CLI/MCP 无命中有清空入口 |

推荐的信息架构方向是“任务分类 + 明确作用域”：账户与安全、外观与语言、工作区（含移动方向簇）、通知、智能体、设备与连接、高级/资源控制、关于与安装。“常用”保留为快捷视图，不另造配置来源；模型、能力、记忆继续保留现有页面。此为重组建议，不代表当前已经有这些一级分类，也不要求一次性改造全部导航。

对于重复内容，区别对待：常用中的主题等是有来源标记的快捷副本，可以保留；证书在安全与安装页同时出现是与任务相关的入口复用，也可以保留，但应指向同一说明与实现。优先消除的是作用域冲突、错误预期和找不到真实功能。

## 四、本次交付检查

- 已核对注册页面数、导航可见数、各自定义块和设置外通知入口；逐项建议均附实际涉及文件。
- 已复用并阅读既有 `results.json`；查看 `mobile-ui-look.png`、`desktop-short-layout.png`，把关键数值和观察写入本文，避免报告只依赖临时文件。原始临时证据未改写，截图未提交进仓库。
- 本次只新增 Markdown 报告；未运行产品测试、未修改设置、未联网、未启动浏览器。文档链接、问题编号、优先级统计与 Git diff 由本次交付检查核对；报告不是独立验收，也不宣称已修复或已完成新的真机测试。

## Top 5 快赢改进清单

按实现范围较小、能立刻降低困惑与失败成本排序；高优先级系统修复仍按上一节推进。

1. **让低高度桌面设置可滚动（SET-04，P1）**：统一内容区滚动，立即恢复被裁切字段的可达性。
2. **复用草稿输入修正专业智能体路径编辑（SET-02，P1）**：失焦/Enter 才规范化与提交，避免逐字 trim、清空回填。
3. **补齐自定义块搜索词（SET-14，P2）**：先覆盖 `codexCommand`、关闭两步验证等实际字段/操作，再逐步实现定位到字段。
4. **在设置中补通知策略直达入口（SET-12，P2）**：复用现有通知设置，让免打扰、预览隐私和分类开关在设置上下文可发现。
5. **非 macOS 禁用 iOS 操作并说明前提（SET-17，P1）**：让平台支持状态直接约束操作，避免用户走入无法完成的安装/连接路径。
