# 容器失败的私有错误证据

## 产品设计与用户故事

只读沙箱中的写操作失败时，底层已取得标准错误，却丢弃它，只留下RSI_DOCKER_COMMAND_FAILED。用户需要从Case的现有证据入口找到实际原因，不能靠重新运行未知操作排查。

## 技术设计

container_failure_evidence.py承担稳定异常、标准错误脱敏/裁剪和每Case的异步上下文捕获。docker_command在已知非零退出后创建诊断；原生检查在内部捕获或预检重新包装仍保留原错误，清理失败不能覆盖最早记录。异常文本保持原错误码，不记录argv、stdin或stdout；标准错误按已有脱敏规则处理，体积截断和遗漏数量显式记录。

ContainerExecutor.run绑定任务上下文；pipeline_runner保留异常边界上的证据，trial_evidence把详情加入私有Case结果。原生执行前的预检失败另存evaluate/environment-failure.json，既有工作流附件可查看；每Case失败通过现有证据JSON入口与results.json可查看；公开GitHub汇总保持简洁且不含标准错误。没有新增页面、模型调用、重放逻辑或模型准入规则，判定和用量字段保持。

## 验收边界

新增Case84，公开合成标准错误与实际夹具一致；机制检查包括真实只读Docker命令。机制验证不作真实任务质量成绩，人工标签、原生阈值和历史全套不改。后续以冻结回执补充最终结果。
