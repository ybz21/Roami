# 模型能力与 Auto 调度

[技术设计（HTML）](technical-design.html) · [统一原型（HTML）](prototype.html#/capabilities/models/gateway)

## Product Design

统一模型类型、输入输出能力、工具、推理、结构化输出、容量、费用与证据视图，供模型设置、Roami Main/Worker、首页和 CLI 共用。能力目录可筛选，详情展示声明与验证的差别。Roami 聚合、固定模型与上游自动路由分别呈现，来源与原生/适配能力单独建模。

对外交付只保留技术设计、原型设计两份 HTML。原始证据、源码与验收记录作为内部支撑资料。

统一入口从 **能力 / 大模型 / 本机网关** 进入，保留“接入与密钥 / 模型目录”和三类目录卡片；顶部按钮可直接回到 [Roami 模型设置](prototype.html#/capabilities/agents/roami)。Roami 页仍对应用户截图，手机经工具 / 能力进入。首页、项目下任务共用同一目录与聚合成员数据。

本轮与会话 `2026-1112-1808-jl57`（本机网关设计，检查点 `21ca98ec`）对照统一；对方工作区只读，保留其生产实现和静态稿。本会话检查点为 `58c750ac`。技术设计增加“与本机网关设计统一”，不是直接把运行代码合进文档分支。合并预演对这两个检查点无冲突。

三个关键口径：目录范围与模型身份分开；`hy4free` 的视觉能力保持未知；Auto 引用网关 `free-pool` 及其保存成员，不扫描全部免费模型。历史 Key 不支持从哈希恢复明文，统一原型只在生成 / 轮换后复制一次。

本次仅交付设计文档，不修改产品代码、生产模型配置、凭据或路由。所有新增命令、配置和错误码均为拟议契约。

## User Stories

- 按图片、音频、工具、推理等能力选择模型，看到明确的未知与不可用原因。
- 通过拟新增的 `roami models` / `roami agent gateway models` 查看相同能力，使用 `--model`（兼容 `-model`）为新对话、执行会话或任务指定模型。
- 指定已配置的 Auto 聚合池，在任务硬约束下复用现有策略调度，不改全局 Main/Worker 默认模型。
- 未来以检查点和持久等待恢复免费长时任务，额度不足不静默转付费。

## Technical Design

技术设计包含能力数据、模块与接口、CLI 契约、长时任务和验收边界；原型设计包含能力目录、Roami 选模和 Auto 调度的交互。扩展已有 Go 网关、目录修订与路径验证，不创建第二套路由/额度准入。Python 传播 Go 决定；前端复用能力选择器和 workspace store。

- `proposal.tsx`：技术设计源码；`model-design-unification.tsx` 记录跨会话的页面归属、共享契约、冲突决定与集成顺序。
- `product-prototype.tsx` / `product-prototype.css`：带实际导航、页面位置和独立流程的当前原型，复用 `useLayout()` 与仓库图标。
- `prototype-models.ts`：统一目录、能力快照、两个明确成员的聚合与仅上游目录示例。Free pool 有三个成员，Coding pool 有两个成员且权重为 3:1。
- `prototype-gateway.tsx` / `prototype-gateway.css`：合并后的网关接入、Key、三类卡片和检查器。目录数据与 Key 元数据由同一原型根组件持有；新 Key 明文只在检查器临时保留。
- `proposal.css`：与仓库设计规范一致的令牌快照、平面布局和手机全屏详情。
- `build.mjs`：通过项目既有 esbuild 依赖构建可直接打开的两份 HTML；不请求 CDN。
- `technical-design.html`：技术设计，内嵌 JS/CSS，离线可用。
- `prototype.html`：交互原型，原图使用同目录相对路径。
- `index.html`：原型的旧入口别名，用于保持此前交付链接可用。
- `model-evidence.json`：2026-11-16 读取的六个公开 OpenRouter ID 的原始字段子集、UTC 时间、来源和完整响应摘要。只读目录，无推理调用。
- `assets/reference-input.png`：用户附件原件的逐字节副本，属于设计输入资料，非 PR 一次性截图。原件仍保留在 `/tmp/clipboard-20261116-113946-6x2v.png`。

构建：先按仓库方式在 `frontend` 安装锁定依赖，再从仓库根运行：

```bash
node docs/design/20261116-model-capabilities/build.mjs
```

简单静态预览可使用以下隔离入口；剪贴板与手机键盘的最终验收使用任务目录内的自签 HTTPS 服务，未启动或修改生产 Agent：

```bash
scripts/dev/isolated-roami.sh /tmp/roami-model-capability-design/instance \
  python3 -m http.server 19376 --bind 0.0.0.0 \
  --directory docs/design/20261116-model-capabilities
```

后续实现必须核对 `hy4free`、`workbuddy-hy4` 的实际候选图；本次不按名称猜测其能力。公开目录中的“声明支持”也不代替当前节点的账号、协议和适配器验证。

延续：[模型源与聚合工作台](../20261114-model-orchestration/README.md)、[现有网关与 Roami 模型绑定](../20261030-智能体模型切换/README.md)。
