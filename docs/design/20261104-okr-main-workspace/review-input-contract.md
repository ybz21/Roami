# 复盘写入的明确契约

关联 #843。设计与实现候选，尚未部署；已有占位复盘保留并由后续真实记录明确纠正，不计为有效成果。

## Product Design

Main 应直接看到保存复盘需要的字段，不用在生产里写“测试”来猜参数。新增有范围的复盘动作只需当前 revision、真实 summary 和可选 actions；项目身份由宿主绑定。保存后返回可核对的最小回执，避免把整份工作区变成一次巨大工具结果。

## User Stories

- Main 先读当前状态，再用准确字段保存有证据的复盘；字段错误得到只读契约，不产生复盘记录。
- 对同一原请求重试时保持业务键与原回执，不因刷新 revision 或更换工具调用而重复写入。
- 复盘涉及“测试”这一正常业务时仍可保存；不做关键词黑名单。
- 最终回复失败不撤销已保存记录；恢复先对账实际回执，不能重新写一轮。

## Technical Design

提供 project_okr_review 与 swarm_project_review 强类型入口，Foundation 使用对应 project/Swarm review 命令。summary 必须是真实非空文本，actions 可为空；revision 使用实际读取值，不能由工具刷新替代用户提供的 CAS。通用 update 的 review 继续兼容，但在节点调用之前校验真实 revision/summary/actions/operationKey 契约，错误只返回公开 schema，不回显私有输入。

复用原绑定项目/Main、Swarm 范围与 Go ReviewOnce。直接 Main 的业务键由原 turn 派生，改稿不能换键制造第二条记录，协调批次沿用原固定 review key。宿主先确认操作回执能力，再提交；同键重试返回原 reviewId，不创建新记录。结果只返回真实项目、当前修订、review 与操作回执；不把字段校验或回执当内容质量审核、平台发布或目标完成。

原 Go CLI/API、现有项目身份和权限不扩展。纯模型内容判断仍需遵守真实用户目标与证据；明确参数契约不能被宣传成可以识别所有不当内容的语义审核器。

## Acceptance

实际 Gateway 覆盖错误字段零节点写入、公开契约无私有值、纠正后原绑定成功；覆盖中文/正常测试内容、空白/错类型/未知字段、跨项目/owner/worker、旧 revision、稳定键重试与错回执。协调路径保持原 batch identity，不开放任意项目或 operationKey。通用 Skill 与实际项目手册同步；原 Main 下一份真实复盘用该契约验收后再关闭问题。
