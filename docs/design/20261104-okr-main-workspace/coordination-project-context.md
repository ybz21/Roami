# 协调回合复用项目只读入口

## Product Design

原 Main 的用户回合与持续协调回合复用 `project_okr_context` 读取当前项目定义、指标与手册。
协调模式继续限定原目标、原项目和原成员；目录执行、配置写入和发布权限保持原有边界。

## User Stories

- Main 不需要因进入协调回合而换一套项目读取指令。
- 项目绑定变化时，旧目标不能读到另一个项目。
- 模型不能通过额外参数指定项目或借只读操作保存定义。

## Technical Design

线上首次持久目标唤醒已实际运行。通用 Main 指引要求读取 `project_okr_context`，但协调工具目录
只接受 `swarm_project_context`，前者返回 `SWARM_COORDINATION_OPERATION_UNAVAILABLE`。
专用入口存在，缺口是通用接口在协调模式中的一致性，而不是开放任意 shell。

将只读 `project_okr_context` 加入协调操作集合。Policy 从当前真实 batch 的 delegation 取得
projectId，放入宿主 binding 的 `coordinationProjectId`；通用 bound_project 在访问平台之前核对
当前会话项目绑定与该值。模型 schema 仍为空，不能传项目选择参数。Gateway 前后仍检查原目标、
来源、分支、lease 与暂停/停止状态，保留原 scoped 入口和已有写入幂等协议。

`project_okr_update`、通用 shell 和发布不因本改动获得权限。旧数据任务不存在的产物仍返回读取
失败，不能为了通过验收补造 manifest 或修改旧失败结果。

## 验收记录

34 项项目只读/协调目录/权限专项通过（15.45s），包含直接工具与真实注册 CLI 别名、项目绑定在
实际读取前变化、模型指定其他项目、配置写入和原始 shell 拒绝。完整门禁与生产复验尚未完成。
此修复还未上线；已上线的 #786 只证明持续目标登记与首次原 Main 唤醒，不代表发布循环完成。
