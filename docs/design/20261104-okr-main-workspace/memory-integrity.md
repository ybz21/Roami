# 团队记忆追加、恢复与长期对话分页

关联 [#687](https://github.com/ybz21/Roami/issues/687)，接续固定 Main、长期成员和群聊设计。

## 产品设计与用户故事

Main 记录新知识时追加到已有团队记忆，能够直接发现具体参数；不拿真实写接口试验字段。
完整编辑仍用于用户修订记忆，替换前保留原文，误写后能够按当前哈希恢复。历史版本位于
项目 `.roami/okr/memory/history/<内容SHA256>.md`，文件页直接可读，不新增一级页面。

长期 Main 的 CLI 历史默认返回一页，保留原对话和分支。需要更早消息时使用服务返回的
olderCursor，不把长历史裁成一个成功返回的损坏 JSON。

## 技术设计

- Store 的追加和替换复用同一项目 bundle 锁与 expectedSha256。追加保留原字节前缀，
  校验合并后的64KiB上限；替换前以 SHA256 文件名保存精确原文，归档失败则不更新当前文。
- 版本与当前文件均通过 os.Root、禁止符号链接的原子发布函数写入；不在任意路径写备份。
- memory API 增加 mode=append；默认替换保持已有完整编辑契约，未知模式在写入前拒绝。
- Main 新增 project_okr_memory_append，只有 content/expectedSha256 两个明确字段，
  宿主固定 project 作用域；首页、其他owner和worker不能调用。CLI memory --help 给出只读契约。
- agent history 默认20条，支持 limit(1–100)、before、branch。agentRequest 读上限加一字节，
  超限明确失败且不输出半截响应；不通过加大无界内存限制掩盖长期对话问题。

## 已验证与待交付

真实项目曾被 Main 试写为5字节 probe。本轮停止受影响两次回复，通过原文和当前哈希CAS恢复，
3497字节与原SHA256一致，Main/成员/任务/历史全部保留。该恢复使用已有生产接口，
不表示本文件所述新追加接口或历史备份已上线。

源码专项覆盖并发追加仅一方成功、精确保留历史、误写后CAS恢复、合并后大小上限、
归档目录逃逸不写当前文件、API未知mode/过期hash、跨项目和worker权限。
真实Main的CLI新二进制只读验证返回3条消息、合法JSON和可续读cursor；旧CLI恰好4MiB截断已复现。
隔离Go专项及17项项目运行时测试通过。证据 `/tmp/okr-memory-integrity-20261105/`；
全量门禁、PR、合入和部署另行补录，当前未部署。
