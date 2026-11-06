# 多 OKR 范围绑定验收（2026-11-07）

关联 #746 / #744。仅本批项目范围与稳定投递实现；尚未部署，没有完成生产团队交接、自动收件箱/协调回合或真机验收，issue保持开放。

- 仓库 full 通过：3824 passed, 48 skipped, 6 subtests passed in 957.77s (0:15:57)；Go全量与运行时lint/format通过。本批无前端源码改动，Vitest未重跑；前端typecheck/i18n/hover/build通过。
- 155项相关运行时专项通过；Go的schema23备份/恢复准入与未来schema24拒绝专项通过。首次full发现Go兼容版本仍为22，已修正后重新完整运行，失败日志保留。
- schema22→23私有备份副本核对60张表，所有原字段/记录哈希一致、原Main和原团队保持、foreign_key_check零错误。新范围字段与去重域外不重写原字节。生产数据库只读，未原地迁移。
- 覆盖SQL失败/外键故障后的完整回滚、外键恢复、触发器/视图/索引保留；旧未保存delivery回执沿用原键，旧创建回执不新建替身；不明旧绑定等待可信Main恢复，多个候选不按最后活跃时间选人。
- 自有roami chrome使用真实ManagedSwarm/OkrMainChat、真实Python Runtime与HTTP SSE，验证两项目同名团队、独立Main/成员、草稿切换、群聊不复制私聊、跨项目消息隔离。真实Go CLI通过该实例私有Unix socket发送同键命令，分域投递、原回执重用和同域改文拒绝通过。Go项目HTTP接口/鉴权为控制夹具，团队记忆内容来自两份私有文件，经CLI读取；受控模型的输入分别只有各自记忆，不冒充生产模型或真实Go项目API集成。
- 15项浏览器/CLI断言、1280/1920/2560/3440及390紧凑模拟无文档溢出。未操作手机；该视口模拟不算真机验收。无产品前端源码改动，图片展示隔离夹具中真实既有组件的运行结果。
- schema23生效后旧schema22运行时不能直接回退；生产激活前需独立准备兼容恢复或向前修复方案，本批未替换已验收的schema22包或迁移生产库。
- 自有QA页、浏览器profile、API/Vite服务与记录的测试tmux实例已清理，私有数据、截图与日志保留。

证据目录：`/tmp/okr-project-scopes-20261107/`，含runtime-final-target.log、go-schema-target.log、live-copy-migration-proof.json、browser-proof.json、CLI回执、cleanup.json、full.log。第一次浏览器比较只因JSON字段顺序不同失败，改为解析后比较并使用新业务键完整重验，未更改产品代码或掩盖日志。
