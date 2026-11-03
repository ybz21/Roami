# 项目 OKR 工作台

入口为真实系统的 `#/projects/PROJECT_ID/okr`，桌面与手机均从项目详情进入。

- [产品、用户故事与技术实现（HTML）](implementation.html)
- [接口与任务规格（HTML）](spec.html)

代码：`backend/okr/`、`backend/api/project-okr.go`、`frontend/src/components/projects/okr/`、`cmd/roami/project-okr.go`。真实演示项目为“Roami 宣传”，不把原型数据写入正式库。

验收：隔离桌面7档布局与真实GitHub取数、修订/证据/Swarm链接，Android ADB真机完整流程通过；full门禁通过，Python3180通过48跳过，最终前端1242通过。详细范围和首版限制见HTML。
