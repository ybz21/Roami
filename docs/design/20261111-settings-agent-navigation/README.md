# 设置中的智能体入口整理

## Product Design

按用户截图移除设置分类中的“模型与连接”和“统一记忆”。模型连接继续由“能力 → 大模型”管理；统一记忆从“能力 → 智能体 → Roami”进入。发布节点不保留空的“智能体”设置组，开发节点仍保留实验工作流。

记忆沿用既有列表、详情、筛选和确认操作。桌面占满能力标签下方的空间；手机复用记忆组件自己的全屏二级页、返回栏和底部导航。

## User Stories

- 在设置中查找设备、外观和账户配置时，不再遇到已迁移的模型入口。
- 管理 Roami 时，可直接打开统一记忆，返回后回到 Roami 配置。
- 打开已有记忆链接时，仍能看到选中的范围、筛选、页码或记忆详情。

## Technical Design

- `settings/registry.tsx` 删除两个页面注册与搜索索引；`SettingsPage.tsx` 删除记忆页的特殊布局和返回处理，移除失去引用的样式。
- `settings/agent-memory-settings.tsx` 迁为 `capabilities/RoamiAgentMemory.tsx`，继续加载项目目录并复用 `AgentMemory`；桌面页头负责返回 Roami，手机由原组件处理返回与详情。
- `AgentCatalog` 根据 `roami/memory` 子路由选择记忆页。`RoamiAgentModels` 增加可选的记忆入口；引导中内嵌的模型配置维持原有内容。
- `normalizeRoute` 将 `settings/agent/memory` 及旧 `env/agent/memory` 映射到 `capabilities/agents/roami/memory`。查询参数仍由原有 hash 路由与记忆导航管理；模型旧链接沿用已有迁移逻辑。
- 复用现有 i18n 文案、布局令牌及组件，不新增样式值或后端接口。
- 返回位置按 [AGENTS.md 的标题栏返回规范](../../../AGENTS.md#back-navigation-starts-the-title-bar)执行：Roami 配置、统一记忆、首页独立记忆页及模型详情的返回控件在标题之前，DOM 顺序与视觉顺序一致；标题栏不换行，长标题省略。

## 验收记录

2026-11-11：使用 `scripts/dev/isolated-roami.sh /tmp/roami-settings-agent-check` 启动隔离 HTTPS 实例，服务端口 18841，前端为本 worktree 的生产构建。没有发送模型请求或修改用户记忆。

- 桌面覆盖 1280、1920、2560、3440 CSS px：设置分类无旧入口；实际鼠标事件能打开统一记忆；记忆正文拥有可用高度，无文档横向溢出；返回 Roami 正确。
- Redmi Note 8 真机：392 CSS px、DPR 2.75、compact/coarse；ADB 点按“统一记忆”和返回按钮，核对路由和画面变化；入口高度 44px；保留单层可见返回栏与底部导航，无横向溢出。
- 中英文、深浅主题，以及带 `memoryView=review&memoryQuery=retained` 的旧链接，检查迁移后的记忆视图与筛选恢复。
- 类型、i18n、hover、生产构建及 quick / full 质量门禁通过。全量测试以 `npx vitest run --maxWorkers=4 --minWorkers=1` 复核，230 个文件、1676 条全部通过；高并发运行中的一条无关 OKR 保存测试，单独复跑 17 条通过。

一次性截图和测量 JSON 保存在 `/tmp/roami-settings-agent-check/`：`desktop-settings.png`、`desktop-memory.png`、`phone-settings.png`、`phone-roami.png`、`phone-memory.png`、`desktop-audit.json`。截图不提交到主分支；如创建 PR，应按仓库规则上传到 `pr-shots`。

### 返回位置修正验收

2026-11-11：四档桌面宽度分别检查 Roami 配置、统一记忆、首页独立记忆和模型导入详情，共 16 组：返回控件是标题栏首个元素、位于标题左侧、同一行且命中正常，实际点击能返回，无横向溢出。英文浅色主题同样验证通过。Redmi Note 8 硬刷新后通过 ADB 点按记忆页左侧返回箭头，确认回到 Roami 配置。

full 质量门禁及 230 个文件、1676 条测试再次全部通过。测量结果为 `back-header-audit.json`，截图为 `desktop-memory-return-before.png`、`desktop-memory-return-after.png`、`desktop-roami-return-after.png`、`desktop-model-import-return-after.png` 和 `phone-memory-return-after.png`，均存放在同一临时验收目录，随 PR #883 发布到 `pr-shots`。
