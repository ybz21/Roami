# Python 测试缓存与检查范围（#728）

## Product Design

测试产生的未跟踪 Python 字节码不是新源码，不应让下一次检查自动扩大到其他 Skill。
本次只恢复既有范围选择，不删测试，不新增跳过开关，不改变全量发布检查。

## User Stories

- 仅改 runtime，测试产生 OKR Connector 的 pyc 后，下一次 full 仍只选 runtime/Go。
- 未跟踪的真实 Python 程序仍进入检查；已跟踪或已暂存的字节码仍保守处理。
- 比较失败、真实删除/重命名和 release 检查保持原行为。

## Technical Design

scripts/dev/quality/python-check-plan.mjs 仅在收集 git ls-files --others 的结果时，
排除文件名以 .pyc/.pyo 结尾的未跟踪字节码。暂存区、已跟踪变更、提交比较及未知范围
不套此过滤；不整体忽略 __pycache__，其内的 .py 仍视为真实源码。
独立临时 Git 仓库覆盖 runtime 改动+生成缓存、仅缓存、真实新增程序以及已跟踪缓存；
保留既有跨目录重命名、删除、共享依赖和未知比较回归。

## Acceptance

修改前新增场景产生3项失败；修改后42项范围选择回归全部通过。
记录 /tmp/okr-python-cache-scope-before-20261109.log 与
/tmp/okr-python-cache-scope-fixed-20261109.log。正常 quick/full 已通过：runtime 4763项/48跳过/6个subtest；四组Skill共248项，Go与前端检查/构建通过。CI及合入尚待完成。
本次不缩小真实 OKR 模板资源改动的既有完整检查，不声称整体CPU或内存下降。
