# 项目 OKR 工作台

最新优先级：[先执行、再展示、最后对话生成（HTML）](execution-first.html)。

执行主线：[真实模型、共享群聊、取消组件与待完成项（HTML）](execution-acceptance.html)。这份记录区分组件通过、完整团队交付与实际平台发布。

浏览器上传：[设计（HTML）](browser-upload.html)、[调用契约与实际字节验收（HTML）](browser-upload-acceptance.html)。成功选择文件与平台上传、提交、公开分别验收。

2026-11-04：当前主线基于已合入 PR648/650 的 main，补齐项目文件、方法与指标看板、按需目标对话工具、团队记忆和真实交付验收；本轮主线尚未部署。

- [总体方案、完整用户故事与技术架构（HTML）](overall-solution.html)
- [集成、桌面/真机及真实宣传验收（HTML）](integration-acceptance.html)
- [六名旧成员交付验收与回收（HTML）](member-acceptance.html)

左栏 `#/okr` 只展示已保存目标；新建时选择关联项目。详情外层为“OKR 与看板 / 具体活动 / 文件”，工作台内为“OKR / 数据看板 / 当前状态”。不是每个项目都有 OKR。只有保存确认的目标才生成项目 `.roami/okr` 文件包，现有旧目标按需迁移。

代码位于 `backend/okr/`、`backend/api/project-okr.go`、`cmd/roami/project-okr.go`、`frontend/src/components/projects/okr/` 与 `agent-runtime/src/roami_agent/` 的项目工具、Swarm、记忆和证据模块。任务、群聊与调度继续复用既有运行时。

本轮 full 门禁通过；Python 3321通过/48跳过，前端184文件/1301测试通过，受影响Go模块race通过。桌面四档×对话开关八组和Android ADB真机检查通过。接口验收使用独立实例及合成项目，没有模型调用，不代表已自动发布或完成日更。

真实“Roami 宣传”的配音/字幕MP4已生成，X保存草稿，B站待登录；均未公开发布，原文案验收2/2未改写为视频或发布完成。详情见验收HTML。

历史记录：

- [首版产品、用户故事与技术实现（HTML）](implementation.html)
- [首版接口与任务规格（HTML）](spec.html)
- [前轮重设计与上线验收（HTML）](acceptance-redesign.html)
- [旧蜂群恢复与验收（HTML）](legacy-recovery.html)
- [活动场景与项目归属修复](../20261104-okr-studio-project-ownership/README.md)
- [原输入/输出交互设计原型（HTML）](../20261030-okr每日行动/interaction-design.html)
