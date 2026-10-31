# 验收

运行`agent-runtime/.venv/bin/python cases/case-78-mech-ns01/scripts/run.py --output /tmp/new-ns-receipt`。

33项、零失败/错误/跳过；事务提交前后、准备/运行状态下取消不执行工作，旧Native回合不再运行，续办进入第二修订；启动错误不伪装完成，停机取消保持中断。实际CLI往返、既有续办和会话存储同时回归。源码与输入冻结，原有测试时限不变，不代替业务质量或独立验收。
