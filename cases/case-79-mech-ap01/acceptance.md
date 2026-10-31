# 验收

`python3 cases/case-79-mech-ap01/scripts/run.py --output /tmp/case-ap01-evidence`。

必须收集父测试及TERM、KILL两个子测试，共3项，零失败、零错误、零跳过。通过pidfd确认子进程退出，并核对其观察到父管道EOF。运行前后校验Go源码、测试和公开输入哈希；隔离实例通过原入口停止。原判定器、历史Case成绩与保存模型配置不变。
