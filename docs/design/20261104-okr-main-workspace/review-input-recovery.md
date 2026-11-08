# 验收与发布输入纠正

## Product Design

Main 输入不符合宿主要求时，失败回执同时说明下一步如何纠正。保持原错误码、任务、执行身份与业务键；不把输入校验误报为账号授权失败，也不通过新成员、空证据列表或绕过校验继续。

## User Stories

- Main 读过磁盘文件但未读取所选留存产物时，知道使用 `read artifact://ID` 完整读取当前轮次文本。
- Main 知道制作任务先验收，之后才能冻结发布版本；等待验收不是账号问题。
- 成员从完整初始化模板获知发布清单的嵌套身份和相对路径基准，无需反复试错。

## Technical Design

`tools/review_input_recovery.py` 为六个已有的验收/准备错误提供固定恢复说明，`ToolGateway` 将其放入失败工具回执的 recovery 字段。原错误码、failed 状态、上下文/角色/原始成员/当前轮次/工作区/哈希检查保留，不自动重试、不扩大权限、不修改任务或发布状态。其他错误不套用这类说明。

现有 Swarm 验收与发布准备工具目录同步说明 `artifact_read` 与 `file_read` 的区别、manifest.identity 的对象结构，以及 files[].path 相对 manifest 所在目录。模板根/内层 AGENTS 引导先读发布手册；完整 assets 与 package.files 同步。

## 真实触发与验证

原项目 Main 在当前 X 第15轮通过 file_read 读取 manifest、verification、业务键及图片，随后四次 swarm_verify 没有成功；所选三个留存文本产物没有对应 artifact_read 回执。宿主拒绝是正确行为。该轮清单另有顶层平铺身份、相对执行目录的路径，独立用宿主解析器得到 INVALID_PUBLICATION_MANIFEST，且文件按清单目录解析不存在。

专项45项通过。真实 Gateway 回归先拒绝缺少产物读取的制作验收，再按提示完整读取留存文本并验收成功；发布回归拒绝平铺身份/正文原文，没有生成冻结版本，修正后同一业务键只生成一条事项且不授权发布。真实线上 Main 的纠正、冻结和发布循环尚未验证，本记录不替代其回执。
