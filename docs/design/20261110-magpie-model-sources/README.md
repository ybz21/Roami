# Magpie 插件模型源

## Product Design

模型目录支持导入文件夹或 ZIP。每个已配置的插件源显示为独立卡片，配置页复用插件声明的登录方式、选项与模型列表。导入和登录是两个步骤；导入不会自动执行登录、签到或模型请求。已有源保留，更新模型列表时保留用户选择。

网关调用 Key 支持自动生成、命名、复制、轮换、停用和删除；完整 Key 仅在生成或轮换后显示一次，持久化哈希。

## User Stories

- 上传官方 WorkBuddy 文件夹或 ZIP，选择中国站或国际站，按插件提供的浏览器登录/API Key 登录并更新模型。
- 上传官方豆包工作插件，在支持的桌面环境中打开独立窗口登录，反代其模型；串行请求，不自动重放取消后的任务。
- 当前 Linux 环境明确提示豆包工作缺少受支持的 macOS/Windows 桌面应用，允许保存导入的插件，不谎报可调用。
- 管理多个调用方 Key，单独撤销一个 Key，不修改模型源登录凭据或 Agent 内部凭据。

## Technical Design

- `internal/modelplugins`：文件夹与 ZIP 共用路径、类型、数量和展开大小校验，导入到内容寻址的不可变包目录。不执行 npm 安装和生命周期脚本。
- `internal/modelplugins/runtime`：固定版本的原版 Magpie Bun host，以 JSON 行 RPC 连接；保留原插件的 auth/config/provider/fetch 行为，不另写 WorkBuddy 专用反代。
- 每个配置源独立运行状态、登录文件、进程和选项。Web 只接收白名单元数据与登录步骤，不返回 auth 文件、loader API Key 或请求头。
- 模型按各自 npm/native API 协议路由，再接入现有网关协议转换、计量与准入。不能将混合协议的 WorkBuddy 模型都视为同一个上游接口。
- 豆包工作使用独立桌面 profile；保留插件的 `maxConcurrency: 1`、文本能力限制与取消语义。操作系统或应用缺失时返回环境错误。

## References

- Magpie runtime: `yetone/magpie@d4b4a188ef2557ca8a8b33a70960bfa5fa0b28ef`，MIT。
- 验证插件：`magpie-community/plugins@ebc7783caeb5025191e7068e544bae95eb8ae616` 的 `packages/workbuddy` 和 `packages/doubao-work`，MIT。

## Acceptance

实现与验收进行中。导入包检查通过不等于已通过登录或真实推理；真实调用结果、平台限制及部署版本单独记录。

## Compatibility boundary

首批兼容对象是上述固定版本的 WorkBuddy 与豆包工作 OpenCode v1 provider 插件。插件自己的名称、登录说明、问题和选项文案作为第三方内容按其语言声明展示；Roami 的按钮、状态、校验和错误均提供中英翻译。

Linux worker 使用 Bubblewrap 独立文件系统、进程和网络命名空间，并使用独立 systemd scope 限制内存、进程数和 CPU。只挂载插件包、自有状态目录、运行时和单个出网 socket。HTTP(S) 出网代理拒绝本机、内网及特殊地址；不共享宿主 Chrome CDP、管理 socket 或用户 HOME。不自动安装依赖或执行 npm 生命周期脚本。

豆包工作在 Linux 可以导入、解析模型、创建卡片及保存配置；其上游插件明确不支持 Linux 桌面推理。当前尚无可用的 macOS/Windows 节点和已登录桌面应用，因此真实豆包调用尚未验收；不能将导入成功计为反代通过。

### Desktop runtime

macOS/Windows 的桌面入口仅允许固定版本豆包工作 0.1.5 的已审阅代码；逐文件规范化校验 8 个运行文件和 manifest，允许 Git 的 CRLF 转换，拒绝代码改动、额外运行文件和 manifest 改动。任意上传包不会因此获得桌面访问权限。桌面 worker 使用独立登录目录及最小环境，不继承 Roami 登录凭据；此入口使用桌面应用本身，不能声称拥有 Linux Bubblewrap 的文件系统隔离。其他插件仍需受支持的隔离环境。

豆包应用由插件通过自己的 profile 启动，保留单请求并发。删除源移除 Roami 配置和 worker，但不关闭桌面窗口或云任务，也不删除正在使用的桌面 profile。上述桌面命令构造、包校验和跨平台编译可在当前机器验证；实际启动、登录、模型菜单与云任务需兼容桌面节点实机验收。

## 桌面二级导航调整（2026-11-11）

桌面能力分类继续横排；模型、用量、定价、网关、语音输入作为左侧竖排导航，右侧内容占用剩余空间并独立滚动。导航不随内容滚走，编辑详情打开和关闭后按可用宽度分配空间。手机保留五栏横排和全屏详情，以保持已验证的紧凑触控布局。使用原有 Tabs 与路由，不改变设置保存和草稿行为。
