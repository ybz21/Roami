# 对话交付文件链接恢复（#846）

## Product Design

Main、群聊和成员对话沿用共享 Markdown 与文件预览。旧消息的本机 file URI 转为
同一来源节点的文件服务地址，用户直接查看原交付；不修改历史消息，不重跑业务写入。
不新增按钮、页面或提示，不改变对话输入框。

## User Stories

- 用户点击旧复盘链接，直接看到已经保存的文件，并能返回原对话。
- 节点切换后，带明确来源的成员消息仍读取原节点文件。
- 远程 file authority、未知协议及畸形编码不能被转换成可执行链接。

## Technical Design

共享 Markdown 在 react-markdown 默认协议过滤之前，仅将已知本机目录的合法 file URI
规范化为编码后的绝对路径；其余地址仍用默认 URL 过滤。现有 agentResourceUrl 将文件
路径送到文件服务，显式 resolveHref 保持优先，成员消息保留原 node 身份。
手机继续使用现有 MobileFilePreview、文件解析与返回栈，不复制新的预览实现。
查询参数、远端 authority、空字节、编码路径分隔符、反斜线及无效百分号拒绝转换；
中文、空格和文件名中的 #/?/% 按路径段编码。片段仍为片段，不误作文件名。

## Acceptance

修复前：真实线上群聊“收口补记”href=null；新增回归两项失败，证明链接丢失。
修复后：52项专项、217个文件/1602项前端全量、typecheck/i18n/hover/生产构建通过。
隔离 QA 服务 18446，仅使用 Root 自有 Chrome 标签。Main 和群聊原消息均恢复文件服务
地址；实际点开现有 main-review-20261109-r26-closeout.md，正文正常渲染，HTTP200、
2381字节、SHA256 12b6af37c220bae1ded1c8ea5c38d0b2553b9c72155145c4c50972e29827e9ad
与原件一致。未重发消息、写业务数据、触手机或改线上服务。

证据：/tmp/okr-file-links-qa-20261109/preview-after.png、
/tmp/okr-file-links-targeted-20261109.log、/tmp/okr-file-links-frontend-full-20261109.log。
普通浏览器预览并非 Android 真机验收；真机与最终生产验收尚未完成，不据此关闭 issue。
