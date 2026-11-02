# fix(agent): bash 转发绕过已禁用的 shell 权限

基线：`bd1871e3`。配置/评测希望保留注册 Roami CLI，但通过 `runtime.tools.disabled_tools.add("shell")` 禁止通用进程执行。此时 `bash` 仍可执行 `scope=host` 和 workspace 的 argv/command 形式，实际产生文件写入。

## 复现

1. 在临时 Runtime 中配置独立工作目录，禁用底层 shell，保留 bash。
2. 经正常 `runtime.tools.invoke` 调用 bash，传入仅在该临时目录创建标记文件的 Python 命令；分别测试 host/workspace 与 argv/command。
3. 预期：`TOOL_DISABLED`，进程未启动，无标记文件。实际：四种形式都执行，`pytest.raises` 的四项反例全部失败。

证据：`agent-runtime/src/roami_agent/tools/foundations.py:425` 的 bash handler 在基线第448行直接调用 `registry.registry["shell"].handler`，绕过 `Tools.validate` 对禁用操作的检查。修复后第446–450行增加转发前检查。独立反例在 `agent-runtime/tests/test_host_execution.py::test_disabled_shell_blocks_foundation_bash_before_process_start`。

影响：任何只允许注册 CLI、禁用 shell 的角色或评测 profile 都不能依赖该禁用标记阻止通用 shell。新对话评测的隔离反例实际发现此问题，只写入测试自身临时目录；没有访问或修改用户业务文件。

修复建议：在转发到底层 shell 前检查 disabled_tools，不影响已经解析到目标操作的注册 CLI。对话评测另外拒绝未解析的 bash/旧 CLI 回退，完全阻止调用真实后台 CLI；保留正常发现、help 和注册命令。

查重：已搜索 disabled_tools 与 shell 禁用。#385（已关闭）是 research 不可用调用的无进展循环，不是已禁用 shell 仍被执行；#443/#445/#446 为综合 RSI 诊断，不覆盖本次四种形式的转发权限绕过。
