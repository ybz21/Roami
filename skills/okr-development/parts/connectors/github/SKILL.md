---
name: github
description: 获取本项目公开 GitHub 仓库的 Star 和 Fork 候选观测，保留来源与时间。
---

读取已确认 repo、稳定 repositoryId、指标映射、日期口径与当前 revision。在授权的受管
工作区运行 scripts/fetch_github.py --repo OWNER/REPO --timezone IANA_TIMEZONE，已确认
仓库必须加 --repository-id CONFIRMED_ID；这些值来自项目定义，不猜测或照抄示例。
首次来源发现没有确认 ID 时可以只生成候选，确认来源后再更新项目。

输出只是候选事实与证据，不是已发布快照；不手写 observations.jsonl 或 current.json。
检查 HTTP200、repositoryId、full_name、计数、采集时间与指标日期。来源不可用时报告
未知，不能填零或补造历史。仓库名相同但稳定 ID 改变时停止，先核对来源。

[evidence 规范](references/evidence.md)说明如何保存和复核原始响应、来源代码与日期。
evidence.http.body 保留原响应 UTF-8 文本，按 UTF-8 重算 evidence.sha256；解析后的
payload 重新序列化不等于原始字节。公开响应头只保留时间、缓存和请求标识，不复制凭据。

当前产品的确认写入仍使用已注册 collect 操作；它会独立取数，不是把 Python 候选批量
写入同一条观测。分开记录两次采集的时间和证据，核对同一来源，不混淆响应 SHA。
未来 Skill 批次提交须等待宿主能力，不能用 shell/SQLite 绕过项目身份或 revision 拒绝。

定时执行是独立配置。没有真实 schedule/nextDue 回执，不说已经每日运行。
