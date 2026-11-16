# 模型能力与 Auto 调度

[打开 HTML 设计文档](index.html) · [公开模型证据](model-evidence.json) · [设计稿验收](acceptance.md)

## Product Design

统一模型类型、输入输出能力、工具、推理、结构化输出、容量、费用与证据视图，供模型设置、Roami Main/Worker、首页和 CLI 共用。能力目录可筛选，详情展示声明与验证的差别。Roami 聚合、固定模型与上游自动路由分别呈现，来源与原生/适配能力单独建模。

本次仅交付可交互 HTML 设计文档，不修改产品代码、生产模型配置、凭据或路由。所有新增命令、配置和错误码均为拟议契约。

## User Stories

- 按图片、音频、工具、推理等能力选择模型，看到明确的未知与不可用原因。
- 通过拟新增的 `roami models` / `roami agent gateway models` 查看相同能力，使用 `--model`（兼容 `-model`）为新对话、执行会话或任务指定模型。
- 指定已配置的 Auto 聚合池，在任务硬约束下复用现有策略调度，不改全局 Main/Worker 默认模型。
- 未来以检查点和持久等待恢复免费长时任务，额度不足不静默转付费。

## Technical Design

完整契约、标准字段、接口和模块边界在 HTML 的“CLI 与配置”“技术设计”中。扩展已有 Go 网关、目录修订与路径验证，不创建第二套路由/额度准入。Python 传播 Go 决定；前端复用能力选择器和 workspace store。

- `proposal.tsx`：中文开发者设计文档与交互；直接复用项目 `useLayout()` 和图标。
- `proposal.css`：与仓库设计规范一致的令牌快照、平面布局和手机全屏详情。
- `build.mjs`：通过项目既有 esbuild 依赖构建可直接打开的 HTML；不请求 CDN。
- `index.html`：生成交付物，内嵌 JS/CSS，离线可用。原图仍使用同目录相对路径。
- `model-evidence.json`：2026-11-16 读取的六个公开 OpenRouter ID 的原始字段子集、UTC 时间、来源和完整响应摘要。只读目录，无推理调用。
- `assets/reference-input.png`：用户附件原件的逐字节副本，属于设计输入资料，非 PR 一次性截图。原件仍保留在 `/tmp/clipboard-20261116-113946-6x2v.png`。

构建：先按仓库方式在 `frontend` 安装锁定依赖，再从仓库根运行：

```bash
node docs/design/20261116-model-capabilities/build.mjs
```

桌面和真机预览使用隔离入口启动静态资料服务，未启动或修改生产 Agent：

```bash
scripts/dev/isolated-roami.sh /tmp/roami-model-capability-design/instance \
  python3 -m http.server 19376 --bind 0.0.0.0 \
  --directory docs/design/20261116-model-capabilities
```

后续实现必须核对 `hy4free`、`workbuddy-hy4` 的实际候选图；本次不按名称猜测其能力。公开目录中的“声明支持”也不代替当前节点的账号、协议和适配器验证。

延续：[模型源与聚合工作台](../20261114-model-orchestration/README.md)、[现有网关与 Roami 模型绑定](../20261030-智能体模型切换/README.md)。
