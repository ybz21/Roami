---
name: okr-development
description: 从用户对话创建或编辑文件化 OKR，生成目标、HTML 看板、Connector Skill、职责、记忆约定和调度草稿。
---

# 生成和编辑 OKR（拟议扩展）

本文件是 canonical okr-development 的设计扩展示例，不另行安装同名副本。
现有项目工具只能保存已支持的协议；模板、草稿、HTML SDK 和通用 Skill 调度尚待接入。

读取绑定项目与当前确认 revision，复用用户已有的目标、来源与分工。新建时可选内容
增长、产品交付或运营模板；编辑时保留原项目 Main、长期成员、provider 对话和历史。
按目标决定 KR、图表与角色数量。未知基线保留未知，不填演示数据。

把草稿放在项目隔离的 draft workspace。输出 okr.json、dashboard.json、dashboard/
下的 HTML/CSS/JS、connectors/<name>/ 下的 SKILL.md 与按需 Python/MCP 资源、agents/
期望职责、AGENTS/记忆位置和默认关闭的调度输入。Connector 是 Skill，不创建另一套
任意命令插件。模板不携带真实凭证、会话 ID、观测或成功状态。

HTML 使用宿主注入的只读 okr.data.read/subscribe，根据返回 JSON 自行渲染；不要
读取服务器绝对路径、数据库或鉴权信息。数据绑定、来源身份、日期、单位、未知值与
失败状态必须一致。使用现有组件和 ECharts，页面专注展示数据。

展示运行预览与必要差异；预览不注册成员、不派工、不启用日更。用完整配置/HTML/
Skill 包校验与基于当前 revision 的 CAS 应用；冲突保留用户草稿并重新核对，不自动
覆盖另一位作者。回读真实文件、快照与界面，不把生成成功当作取数成功。

职责登记、任务执行和定时启用分开核对真实回执。缺少来源授权或每日时刻/时区时
保持关闭提案；未知执行恢复同一 run。Skill 内的 Python/MCP 只提交有证据的候选数据，
由宿主检查并发布确认快照，禁止直接覆盖 current.json 或 runtime SQLite。
