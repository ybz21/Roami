# 侧栏会话派生层级

## Product Design

侧栏回答「有哪些会话、谁由谁派生」，以项目和会话身份为主。移除以 worktree 为父层的分组、重复名称、类型说明、目录会话数量、跨目录来源副标题与空闲 worktree 展开入口。

- 项目下面直接展示顶层会话，每个会话只出现一次。
- 子会话、孙会话按记录的 `parent` 逐级缩进，细线表达派生关系。同一目录中的独立会话保持并列，跨目录派生的会话仍挂在父会话下面。
- 会话行只保留品牌/终端图标、名称、必要状态和顶层会话的活动时间。当前会话单独高亮，父会话不汇总子会话状态。
- 会话菜单提供打开、重命名、派生与关闭；目录与 worktree 信息在项目详情、Git / Worktree 面板等原有入口查看。
- 目录归属继续作为打开会话的内部目标，不影响派生层级。缺失父节点或循环记录回退为可达根节点，不按 RSI 名称前缀推断亲缘。
- 项目折叠状态沿用本地持久化；粗指针行高至少 44px。

[层级示意](proposal.html)。历史验证过程保留在 [验收记录](acceptance.md)，前两稿以 worktree 为可见父层的方案已被本稿替代。

## User Stories

1. 我需要一眼找到 RSI 主会话，并看到它派生的回归、门禁与数值验收会话。
2. 两个会话即使在同一目录中独立创建，也不应被画成上下级。
3. 子会话在独立目录验证时，我仍需要看到它的父会话，点击后进入正确目标。
4. 侧栏不重复展示同名容器与会话；需要查看代码目录时再打开相关详情。
5. 我首先读取启动消息中的任务正文，随后再看准备事项与本机能力。

## Creation and Prompts

同一任务的回归、数值验收、门禁等辅助工作先复用已有会话；确需新开时优先从当前会话 fork。侧栏会话菜单、终端与目录入口在有可用父会话时使用 fork 接口，失败不降级为无关顶层会话。

总入口简报依次为 `# 任务：`、原始任务文本、`# 开工准备`、本机能力说明。新建 worktree、进入已有分支、普通目录与文件启动 Agent 的入口共用规则。默认能力模板增加复用和派生优先策略；历史原版模板自动升级，用户自定义模板继续保留。

## Technical Design

- `frontend/src/components/shell/ProjectTree.tsx`：在项目内构建整个会话森林，直接渲染根节点及派生子节点；不创建 worktree 导航层。
- `frontend/src/components/shell/session-lineage.ts`：视图节点保留真实 TreeTask，打开子会话时使用其自身目标；处理失联父节点与环。
- `frontend/src/index.css`：只保留会话根列表、子节点缩进和连接线；复用颜色、字号、间距与触控令牌。
- `internal/session/collect.go` 与 `internal/sessionstore/sessmeta.go`：平铺 `/sessions` 返回已记录的 parent/created_by；复用当前会话集合，不增加 tmux 扫描。
- `frontend/src/app/useSessionDirectory.ts`：保留 parent，稳定引用比较包含关系变化。
- `frontend/src/app/useProjectActions.tsx`：明确选择的父会话优先，继而使用当前会话或目录中可用会话；没有可用父会话才独立新建。
- `kickoff-brief.ts`、中英文简报文案、默认能力模板及会话技能：任务置顶，统一复用与 fork 优先；模板按精确摘要升级。
- 路由、真实目录归属、状态刷新与手机一级导航沿用既有实现。没有新增请求和轮询，也不声明 CPU 或内存收益。

## Acceptance

真实组件覆盖父/子/孙、多根会话、同目录无亲缘、跨目录派生、等待、休眠和互审；桌面四档宽度、中英文深浅主题及 Android 真机触控，见 [acceptance.md](acceptance.md)。截图只上传 PR 的 `pr-shots` 分支。
