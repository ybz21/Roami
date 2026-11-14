# 市场技能包容量修复

## 产品与用户故事

用户从市场查看 `ui-ux-pro-max` 时，完整脚本和数据包被 384 KB 的旧限制拒绝，
详情页显示 `MARKET_PACKAGE_TOO_LARGE`，无法安装。用户应能预览完整内容、选择安装位置，
并在节点重启后继续使用同一版本的文件。

## 技术设计

沿用当前完整包和固定来源版本的安装方式，不裁剪数据、脚本或许可证。

| 层级 | 限制与实现 |
| --- | --- |
| 解码文件合计 | `skill_package.py` 的 `MAX_PACKAGE_BYTES` 为 8,000,000 字节 |
| 安装请求与单条记录 | `MAX_PACKAGE_PAYLOAD_BYTES` 为 12,000,000 字节，容纳 Base64、说明和元数据 |
| skills.sh 快照 | 请求显式使用同一 payload 上限，避免默认 2 MB JSON 限制截断合法内容 |
| 所有注册记录合计 | `capability_imports.py` 的 `MAX_IMPORTS_BYTES` 为 32,000,000 字节；写入和重启读取一致 |
| 浏览器流 | 每个 NDJSON 帧最多 12,000,000 字符；完整帧和残留帧分别检查，同一网络块可包含多个合法大帧 |

8 MB 能容纳本次观测的约 3.61 MB 技能包，并保留增长空间。32 MB 是所有注册记录的总限制，
不会随着技能数量无界增长。文件数仍限 100；路径、符号链接、归档解压、私有目录和文件权限检查保留。
本次只修改容量与传输处理，不调整页面样式或新增产品文案。

## 验收证据

- 上游：[nextlevelbuilder/ui-ux-pro-max-skill](https://github.com/nextlevelbuilder/ui-ux-pro-max-skill/tree/6ae86f61f520d6ca229d2f40e070410638c908c5)。固定提交 `6ae86f61f520d6ca229d2f40e070410638c908c5`，76 个文件、3,611,761 字节（含根许可证）。
- 实际下载后安装到隔离的 local、Claude、OpenCode、Roami 四个目标，逐文件与下载字节比对一致；重建 Runtime 后说明及包路径恢复成功。未执行上游脚本。
- 回归覆盖 4 MB 数据包的 GitHub 下载、归档与授权快照、HTTP 创建和更新、保存与重启；超出 8 MB 或 100 个文件仍拒绝；路径越界与符号链接原有测试通过。
- 浏览器回归覆盖同一网络块中的两个大帧，以及带换行和无换行的超限帧。
- 定向回归 67 项通过；前端 Vitest 253 个文件、1824 项通过。`quality/check.sh full` 通过，包含 Go 全量测试、Python 4898 项通过 / 48 项跳过 / 6 个子测试通过，以及 typecheck、i18n、hover、生产构建和策略扫描。
- 桌面生产构建实际请求市场技能，完整显示说明、76 个文件和可用安装按钮。
- Redmi Note 8 经 LAN HTTPS 加载同一生产构建，`compact` / `coarse`，392 CSS px，文档无横向溢出；真实触摸搜索打开技能详情，完整接收 76 个文件，安装按钮可用。合成触摸滚动使详情 `scrollTop` 从 0 变为约 348；触摸返回后搜索输入保留。
- 截图通过 `scripts/dev/pr-shot.sh` 存到 PR 的 `pr-shots` 路径；原始日志和图片保留在 `/tmp/roami-market-package-evidence/`，不提交一次性图片。

`quality/check.sh quick` 与 `full` 均通过；最终提交信息见对应 PR。
