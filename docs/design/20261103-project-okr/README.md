# 项目 OKR 工作台

桌面左栏有独立 OKR 入口 `#/okr`，只展示已保存目标；新建时才选择关联项目，进入 `#/okr/PROJECT_ID` 搭建；手机项目顶栏同样可进入。原有项目详情入口 `#/projects/PROJECT_ID/okr` 保留。

- [产品、用户故事与技术实现（HTML）](implementation.html)
- [接口与任务规格（HTML）](spec.html)
- [重点重设计与上线验收（HTML）](acceptance-redesign.html)

代码：`backend/okr/`、`backend/api/project-okr.go`、`frontend/src/components/projects/okr/`、`cmd/roami/project-okr.go`。真实演示项目为“Roami 宣传”，不把原型数据写入正式库。

验收：本轮桌面7档布局、Android ADB真机两个标签与独立对话流程通过；集成 full 门禁通过，最终前端174文件/1261测试通过。本轮未改Python；首版Python3180通过48跳过。详细范围、上线树和限制见验收HTML。

最新设计：目标详情分“OKR 与看板 / 具体活动 / 文件”；看板带按需创建的新 Main Agent 对话，活动复用关联蜂群。详见 HTML 的修订章节。

页面层级：项目页头后直接进入三个标签；目标摘要和配置编辑器归属“OKR 与看板”，编辑时仍可切到活动或文件并保留草稿。

- [升级后的旧蜂群恢复与验收（HTML）](legacy-recovery.html)

- [总体方案：目标、方法、项目文件、团队记忆与真实交付（HTML）](overall-solution.html)

- [旧成员交付验收与回收（HTML）](member-acceptance.html)
