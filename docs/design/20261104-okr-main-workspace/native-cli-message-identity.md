# 原生 Main 的群聊署名与自我唤醒

关联 [#689](https://github.com/ybz21/Roami/issues/689)。真实宣传项目发现 Main 在 shell 中调用
公共 swarm say 汇报进展；其人类署名又产生新的 Main 请求。一轮取数结束后仍会反复核对，
用户看到的署名也不可信。

## 产品设计与用户故事

用户在页面群聊或普通终端发消息，继续唤醒本项目原 Main。Main 自己报告进展时显示为 Main，
不创建新的用户请求；成员继续使用真实 task/run/revision 身份。既有历史不重写，不给 CLI
增加能够自称 Main 的 --as 参数。

## 技术设计

原生 shell 由宿主通过子进程环境携带 ROAMI_AGENT_CALLER_ROLE。公共 CLI 的 say 在该标记
存在时、连接运行时前明确拒绝，并给出已注册 post 的使用方式。该标记只限制误用，不能授予
任何身份，也不是恶意 shell 的安全隔离边界。环境覆盖仍在 provider凭据排除之前执行，保留
既有工作区 Git 环境隔离和取消流程。

正确入口保持既有 `roami swarm post --input JSON`：原生 Main 直接调用工具目录给出的注册
命令，不加 cd/复合 shell 包装。Foundation 将它留在当前活跃工具上下文，通过原 Swarm/owner/
conversation 校验后署名 Main；不会执行公共宿主 CLI。普通人类 CLI 的 say 不受影响。

## 验收记录

Go 专项验证 Main/worker/research 的原始 say 在创建客户端前被拒绝；Python 真实子进程确认
三种角色标记、环境覆盖不能重新注入已排除凭据。真实 Runtime/SQLite/Foundation CLI 回归确认
Main post 署名、同工具重放幂等且 turn 数不增加；原命令目录和 host执行专项也通过。
初次用例忘记计入建群时已有的人类目标消息，已按真实初始状态修正并重验。证据
`/tmp/okr-main-cli-20261106-targeted.log`，完整质量门禁与发布记录另行补录。当前未部署此保护。

完整 quick/full 均通过，Python 各 3669 passed / 48 skipped；full 的 Python 阶段为 995.57 秒，Go全量、前端静态/构建及审计通过。最终后续提交只补本页和入口文档，运行时代码保持 c145bf65 原样；CI按完整PR差异再次核验。
