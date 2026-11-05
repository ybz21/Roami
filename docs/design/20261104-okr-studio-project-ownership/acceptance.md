# 原型验收 · 2026-11-05

本轮只验收静态交互原型，不等于产品功能、模型行为或真实采集验收。

- 运行态与 Studio：1280、1920、2560、3440 CSS px，均无文档横/纵溢出。
- 协作收起后对话获得宽度，Main 草稿保留；Main/群聊/成员草稿分离，场景选人回到对应对话。
- 成员原对话预览保留稳定身份的示意，不创建真实 session；完整 provider attestation 仍待实现。
- OKR、数据看板、团队记忆、项目根文件可切换；每个指标一张卡，缺失观测显示未知。
- Studio 三个模板可选，新增 B 站指标、Skill 内部实现与每日时间能形成草稿；刷新保留。
- 模板只更新期望职责，已有四名成员与原 Main 保留；新模板指标没有观测时保持未知。
- 保存冲突保留草稿与原应用版本；不自动覆盖或启动执行。预览 iframe 不回写 Studio 草稿。
- 390×844 粗指针模拟：运行态联系人与场景开关、Studio 预览返回、内部滚动与边界通过。
- 浏览器未发起任何 /api/ 请求。没有模型、真实消息、项目写入、派工、取数、调度或手机操作。

证据：`/tmp/okr-runtime-studio-design-20261105/acceptance.json`、`verify-final.log`、
`source-hashes.json`，以及 runtime/studio/dashboard/implementation 的截图。
原型脚本语法、Conventional Commit 与 quick 门禁通过；本次只改 docs，Go/Python
按仓库范围规则跳过。中文是设计文档/原型文案，不作为产品 i18n 的绕过方式；正式实现
仍用现有 i18n、useLayout 与 ConversationComposer。

本轮保留前一版 index 的 revision 快照，设计继续在这两个目录演进。真实触控与上线
验收仍需在后续实现批次按授权执行，不能把本文件记作完成 #656/#658/#679。
