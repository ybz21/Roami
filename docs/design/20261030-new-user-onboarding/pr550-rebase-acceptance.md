# PR #550 适配与验收

2026-10-31。分支 `feat/new-user-onboarding` 先 rebase 到 `b991fff83f5aa6d17a6656d0397bc52296b4411b` 适配模型配置，收尾时继续同步到 `origin/main` 的 `b1fefaf2`（PR #551），完整包含 [PR #550](https://github.com/ybz21/Roami/pull/550)。合并后的引导遵循新的模型归属，原型 HTML 保留为历史设计快照。

## 合并与兼容

- rebase 前将全部已跟踪和未跟踪改动保存在 stash `6a0453c43daf38180770fba4a445bf1ed50b8ead`；成功更新分支后恢复，保留备份。
- 收尾同步 #551 前再次保存 stash `d2f8e3f397a679c3f3aad6f4aab31110b46636b6`；最新 rebase 无冲突，未覆盖任何未提交改动。#551 只涉及音频证据展示和文案，重新运行最终前端全套检查。
- 解决执行智能体目录、旧设置表单和中英文文案四处冲突。旧设置表单最终完整保留上游实现，不再承载引导专用配置。
- 第一步改为复用 `ModelHub` 和 `RoamiAgentModels`：统一管理模型源、保存模型、分别选择主 / 后台模型、确认应用，然后验证可用性。新来源默认使用主智能体兼容的 Chat Completions 协议。
- 保留 #550 的 Roami 配置入口、原厂 / 自定义切换、安装前禁用、旧连接恢复和真实配置回读。Roami 配置页仍不启动专业智能体轮询。
- 引导中嵌入模型源和模型详情，手机只有全局顶栏和一个滚动容器；返回详情列表、模型选择和引导步骤都有正确路径。
- 能力介绍补充「大模型」，共八类；设置介绍不再指示用户去旧表单填写模型密钥。

## 验证证明

统一网关的回环 URL 与模型别名不会随着上游密钥改变而改变，因此只比较运行时配置不足以证明当前来源可用。

网关保存目录时原子维护私有 `agents/model-catalog-revision`，内容为每个模型实际协议、主备策略及上游路由和凭据的摘要；不包含上游地址或密钥原文。目录事务进行中暂不发布稳定摘要，提交后才发布，避免失败重试误保留旧证明。

主 / 后台模型和专业智能体仅比较实际使用的模型摘要。相关来源凭据改变，即使别名相同，也要求重验；新增无关来源或模型不重置已有验证。验证过程中使用的摘要变化，则拒绝写入证明。主模型代理等待时间单独使用已有的 100 秒预算，普通 API 仍使用 15 秒预算。

## 自动检查

- 最新 #551 基线：typecheck、i18n（4699 keys）、hover、155 个 Vitest 文件 / 1139 项测试、生产构建通过。新增用例包含选模草稿重入恢复，恢复后仍要求应用与验证。
- #550 适配阶段运行 `scripts/dev/quality/check.sh full` 通过：Go 全仓、Python 2748 passed / 47 skipped（600.91 秒）、前端类型 / 翻译 / hover / 构建、密钥及文件策略检查。
- 随后细化实际模型摘要比较，再次运行 `go test ./...`、Python 验证模块 ruff 和四项测试、相关 Go 摘要断言，全部通过。#551 只有前端变更，继续重跑完整前端检查。
- 覆盖相关来源凭据改变、无关来源新增、验证期间配置改变、私有证明、失败撤销、Roami 配置不额外轮询、原厂模式与安装状态保留。

## 实际产品

隔离目录 `/tmp/roami-onboarding-pr550-00ac`。通过仓库隔离入口启动 HTTPS、Go API、Python runtime 和模型网关；使用全新专用 HOME、Codex / Claude / Pi / XDG 配置目录。主模型来源为本地 SSE 服务。任务启动命令显式指定测试程序的绝对路径，不依赖登录 shell 的 PATH；调用日志确认实际进入测试程序和本任务项目目录。本轮未调用用户原生智能体账号或外部模型服务。

桌面从空安装走通：首次首页、添加统一模型源、添加模型、应用到 Roami 角色、最小调用验证、Codex 验证、原厂模式详情、创建普通目录、提交首个任务。服务端保存真实项目和会话及引导完成状态，测试程序记录 `task:/tmp/roami-onboarding-pr550-00ac/test-project`。

最终隔离节点验证：新增与主智能体无关的来源及模型后，主智能体和原厂模式 Codex 的 `verified` 均保持 true；再更改主智能体实际使用的来源凭据，模型别名保持原值，只有主智能体变为 false，原厂 Codex 保持 true。之前已通过真实页面观察到待验证及下一步禁用，重新验证可恢复。[实际 API 断言](/api/file/tmp/onboarding-pr550-route-evidence.json)。

## 手机与布局

- Redmi Note 8、Chrome 154、392 CSS px、coarse、LAN HTTPS。实际 ADB 点按设置中的引导入口、主智能体、模型源列表、来源详情和返回栏。
- 来源详情标题正确，只有一层顶栏。真实聚焦名称字段，键盘打开时输入框可见，辅助页脚和四项底栏隐藏；内容仅由 `onboarding-scroll` 滚动。已保存密钥为空值占位，不回显。
- 真机前台随后被其他测试页面占用，停止继续发送物理触控；未将执行智能体模式页记作本轮新增真机通过项。该页保留 #550 的模式组件，并通过浏览器布局和组件测试验证。
- 主智能体、模型源列表、来源编辑、新模型编辑、Codex 模型页和能力介绍，在 320 / 390 / 820 / 1100 / 1280 / 1600 / 1920 下共 42 个组合均无横向溢出、文档滚动、缺失手机返回栏或底部动作越界。[布局断言 JSON](/api/file/tmp/onboarding-pr550-layout.json)。

## 截图

- [统一模型选取 · 桌面](/api/file/tmp/onboarding-pr550-model-desktop.png)
- [Codex 原厂模式 · 桌面](/api/file/tmp/onboarding-pr550-agent-desktop.png)
- [首个任务 · 桌面](/api/file/tmp/onboarding-pr550-task-desktop.png)
- [能力八类介绍 · 桌面](/api/file/tmp/onboarding-pr550-modules-desktop.png)
- [主智能体 · Android](/api/file/tmp/onboarding-pr550-model-phone.png)
- [模型源与软键盘 · Android](/api/file/tmp/onboarding-pr550-source-keyboard-phone.png)

截图保存在本机供 review；未创建 PR，不上传一次性图片到主分支。

## 清理

停止本轮匹配专用 `ROAMI_HOME` 的服务进程，tmux 仅通过该目录的 `isolated-roami.sh --stop` 清理。关闭本任务桌面和手机测试页、移除专用 ADB 转发；未关闭其他会话或浏览器页面。改动保留在工作区，未提交、推送或部署。
