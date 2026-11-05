---
name: github
description: 获取本项目公开 GitHub 仓库的 Star 和 Fork 候选观测，保留来源与时间。
---

读取已确认 repo、指标映射、日期口径与当前 revision。在授权的受管工作区运行
scripts/fetch_github.py --repo OWNER/REPO --timezone Asia/Shanghai。
输出只是候选事实与证据，不是已发布快照；不手写 observations.jsonl 或 current.json。

检查 repositoryId、full_name、计数、采集时间与指标日期。来源不可用时报告未知，
不能填零或补造历史。当前产品的真实写入仍使用已注册 collect 操作；未来批量 Skill
提交须等待宿主能力，不能用 shell/SQLite 绕过项目身份或 revision 拒绝。

定时执行是独立配置。没有真实 schedule/nextDue 回执，不说已经每日运行。
