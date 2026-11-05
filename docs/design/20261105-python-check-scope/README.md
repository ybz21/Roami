# 按变更范围运行 Python 与 Skill 检查

跟踪：[#660](https://github.com/ybz21/Roami/issues/660)。不删测试，只减少与变更无关的调度和依赖安装。

## Product Design

纯前端调整不应等待办公软件、视频工具和无关 Python 套件。修改一个 Skill 时仍检查该 Skill 的全部程序和测试；共享依赖或无法确定范围时扩大检查。发布保留显式完整回归入口。

## User Stories

- 调整 OKR 界面时，只等待前端及仓库静态检查，不安装 LibreOffice 或 ffmpeg。
- 修改视频 Skill 的脚本、资源或配置时，运行其完整 Ruff、格式和 pytest 检查。
- 删除、跨目录移动文件或修改共享依赖时，不因路径筛选漏掉原来的使用方。
- 发布维护者运行 `scripts/dev/quality/check.sh release`，不依赖当前分支是否干净。

## Technical Design

`python-check-plan.mjs` 是本地和 CI 唯一调度规则，输出 runtime、四个 Skill、Go 和 Python 环境需求。`python-check-scope.sh` 保留旧布尔接口；`python-skill-check.sh` 执行原工作流中的完整 Skill 命令。`check.sh` 消费计划，工作流用同一个计划决定 Python、办公和视频依赖安装。

| 变更 | 检查范围 |
| --- | --- |
| frontend、文档 | 静态检查、前端检查；full 增加构建 |
| 单个已知 Skill 的任意文件 | 对应完整 Skill 套件 |
| Agent runtime 程序、资源、迁移 | runtime 与 Go 集成 |
| Go 代码、模块与领域资源 | Go；保留其真实 Python 桥接环境，不额外跑 runtime pytest |
| 共享依赖、canonical cases、未识别 Skill、未知路径 | 全部 |
| 质量脚本和质量/发布工作流 | quick：调度回归与静态检查；full：完整重演检查链路 |
| 比较历史缺失或 Git 不可用 | 全部 |

quick 优先暂存区，避免把不在本次提交中的改动混入；full 检查整个分支与工作区。CI 明确传入完整 PR base/head，不能只看最后一次推送。使用 NUL 分隔和 `--no-renames`，删除和移动前后的路径均参与判断。新增资源和文件与源码同等处理。release 无条件扩大到全部检查，没有跳过检查的环境开关。

Go 测试会调用真实 Python harness，因此 Go 的计划同时要求 uv 可用，避免因依赖缺失静默跳过桥接回归。纯前端不调用 Go 测试。前端 i18n 工作流保留 PR、merge group 和 main push，取消功能分支 push 的重复运行及 pr-shots 图片分支构建。

已选套件的系统依赖在 Go、runtime pytest 之前统一预检，单独运行 Skill 也复用同一预检。缺少 ffprobe 等工具会先失败，不必等长套件跑完才发现环境问题。

## Acceptance

调度测试用真实临时 Git 仓库覆盖路径、资源、删除、重命名、完整 PR、多次提交、换行文件名、暂存区、历史缺失、Git 缺失与发布模式。工作流另经 actionlint 校验。

实际执行（2026-11-05，同一主机、相同产品源码、工具已准备，秒为墙钟）：

| 场景 | 计划与实际执行 | 耗时 |
| --- | --- | --- |
| 纯前端真实历史范围 `b063a68c^..b063a68c`，旧调度 | Go、前端完整检查/构建，外加四个无条件 Skill | 236.215 秒 |
| 相同范围，新调度 | 仓库静态检查和前端完整检查/构建；没有 Go、Python 或 Skill | 101.227 秒 |
| 单视频 Skill 资源变更 Git fixture | 只选择 video；真实视频套件 Ruff/format/35 项 pytest 全过 | 2.896 秒 |
| 共享 Python 依赖 Git fixture | runtime、四个 Skill、Go 全部选中；相同全量计划用于本 PR 的真实共享工作流改动 | 见下文分项 |
| 缺少 ffprobe 的负例 | 在 Go/runtime 测试前报错；没有进入长测试 | 4.773 秒 |

纯前端同机样本减少 134.988 秒，约 57.1%；四组有效 Skill 测试共 248 项保持原样。此前 #671 CI 的主门禁 11 分 34 秒后，还花 8 分 51 秒运行办公依赖/报告、6 分 40 秒运行视频依赖/检查；不同主机和安装条件不可直接与上表混算。

全量计划已实际执行 Go 全套，runtime **3518 passed / 48 skipped（891.05 秒）**，presentation **79 passed**，tabular **118 passed**，market **16 passed**。第一次本地 full 在末尾因 ffprobe 缺失退出，没有记作整条 full 通过；私有目录补齐与 CI 一致的 ffmpeg/ffprobe 6.1 后，视频 **35 passed**，前端检查/构建完成。最终 PR CI 仍须完整执行并通过全部选中检查，不能用分流的前端基准冒充本 PR 门禁。

对比复用了旧 6f1825a2 的核心质量脚本与原四个 Skill 命令，固定当前产品源码；旧布尔适配器在该真实前端范围仍返回 false。不是回滚产品，也不包含系统安装时间。办公和视频依赖仅在 `/tmp/okr-ci-scope` 私有前缀准备，未修改系统包、线上服务或模型配置。单 Skill 与共享依赖的选择来自独立 Git fixture，实际测试执行仓库原套件，不把 fixture 当产品实现证据。

证据：本机 `/tmp/okr-ci-scope` 中的 `candidate-full.log/json`、`frontend-before.log/json`、`frontend-after-final.log/json`、`video-selected.log/json`、`dispatch-fixture-plans.json`、`dependencies-early-fail.log/json`；PR 提供公开截图。没有产品界面改动，不操作手机。以上只说明检查等待变化，不声称产品 CPU 或内存减少。
