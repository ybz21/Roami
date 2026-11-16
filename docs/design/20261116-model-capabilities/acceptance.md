# 设计稿验收 · 2026-11-16

范围：仅 HTML 设计文档与页面内演示。未实现产品模型能力、CLI 选模或 Auto 调度；未调用真实模型生成，未修改生产模型、账号、密钥、额度或路由。桌面使用本任务专用 Roami Chrome 标签页，手机使用 Redmi Note 8 的 Chrome 真机。

## 内容核对

- 对照现有 `CatalogModel`、源模型详情、角色绑定、CLI 帮助、执行 spec 与 Python native 任务校验，区分现有基础和拟新增契约。
- 通过公开 Models API 逐项匹配附件中的六个 OpenRouter ID；原始字段子集、抓取时间与响应摘要保存在 [model-evidence.json](model-evidence.json)。这些是上游声明，尚未验证本节点链路。
- 其中五项为具体模型，`openrouter/free` 为上游自动路由。五个具体模型中三项声明图片输入；计入路由共四项。两个本地名称保留未知，不根据名称断言聚合、图片或免费能力。
- 附件原件与设计输入副本 SHA-256 相同：`352a8d6f380f0e7d690165b38617c4be7ca788c114ce8bc7a1c1f5afe016464e`。
- 新增命令、JSON 字段和错误码在文档中明确标记为提案。开发者文档使用中文，符合仓库 i18n 的文档例外；未增加产品硬编码文案。

## 浏览器与真机

测量明细见 [acceptance.json](acceptance.json)。交互通过 CDP 的真实鼠标/触摸输入并核对 `elementFromPoint`；没有以 DOM `click()` 代替命中测试。

| 桌面 CSS 宽度 | 详情关闭时目录宽度 | 详情打开时目录宽度 | 验收 |
| --- | ---: | ---: | --- |
| 1280 | 1001 | 641 | 文档无横向溢出；关闭释放 360px |
| 1920 | 1641 | 1281 | 同上 |
| 2560 | 2281 | 1921 | 同上 |
| 3440 | 3161 | 2801 | 同上 |

- 桌面内容容器高 940px（1000px 视口减真实 60px 页头）；文档本身不滚动，`main` 承担纵向滚动。深浅主题均打开检查。
- 图片筛选得到四项，叠加具体模型类型得到三项；添加音频条件为空态。详情可打开、关闭，宽度完全归还。
- Roami 选模复用全部演示能力条件；图片条件下包含四个公开条目与一个按请求筛选成员的聚合示例。聚合类型筛选仅留下该池。Main/Worker 切换保留各自页面内选择。
- Auto 图片与工具条件得到三个声明候选；要求已验证后为空池，模拟额度耗尽后显示等待且不转付费。未将未知验证、真实延迟或余额伪造为通过。
- Redmi Note 8：约 393 CSS px，`compact/coarse`。实际触控完成图片筛选、全屏详情、返回保留筛选、Roami 选择与 Auto 计划。详情覆盖全部可用视口；真实滚动使 `main.scrollTop` 从约 6295 增至约 6644。
- 最后一轮同时检查 `document` 和 `main` 的横向边界。修正了技术表格的 grid 最小宽度造成的内部横向溢出，并让 checkbox 保持 16px 视觉尺寸、由 44px label 提供触控区域。
- 桌面与手机运行无 JavaScript 异常。本稿为独立开发者文档，产品顶栏、四项底栏、软键盘与安全区的完整业务验收列为未来产品实现的门禁，不冒称本次已实现或验收。

## 检查与交付

- `node docs/design/20261116-model-capabilities/build.mjs` 成功，HTML 内嵌 JS/CSS，无 CDN 依赖；源码复用现有 `useLayout()`、图标和令牌。
- `scripts/dev/quality/check.sh quick` 通过，包括 CLI 审计、shell 语法、Go 格式、i18n、hover、前端 typecheck、secret scan 与 staged policy。
- 本次仅修改 `docs/design/**`。Python/Go 运行测试按质量脚本范围跳过；没有产品 frontend 改动，不运行无关的全量 Vitest 或生产构建。
- `git diff --check` 通过。原图与 JSON 相对资源保持在同目录，截图只放本机验收目录及 PR 的 `pr-shots` 分支，不提交到主分支。

本机验收目录：`/tmp/roami-model-capability-design/`，含 browser-verification.log、verification.json、quality-quick.log 与桌面/手机截图；一次性验收脚本为该目录的 `verify.mjs`。静态服务通过仓库隔离入口启动，收尾通过同入口 `--stop` 核对并清理测试服务器。
