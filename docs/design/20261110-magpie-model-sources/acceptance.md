# 验收记录

## 已完成

- `scripts/dev/quality/check.sh quick` 与 `full` 通过；未修改 Python，按仓库检查计划跳过 Python 检查。
- 前端 223 个测试文件、1,611 项测试通过；typecheck、i18n、hover 与生产构建通过。
- Go modelplugins/modelgateway/agentproxy 的竞态测试通过。
- 通过显式 `ROAMI_MAGPIE_FIXTURES`、`ROAMI_MAGPIE_BUN` 运行未修改的官方 WorkBuddy 0.2.26 和豆包工作 0.1.5：分别返回 2 个、1 个 provider，均含模型与登录方式。
- 真正的 Bubblewrap/systemd 隔离进程完成 2 MiB 流式回复、背压、取消、并行管理请求验证；公共 TLS 出网验证通过，内网和特殊地址拒绝测试通过。
- 网关集成测试完成 OpenAI 请求至插件 Anthropic 原生请求的转换、上游独立凭据、API 模型 ID、用量归属、参数修改后的旧缓存失效及旧参数结果拒绝回填。
- 官方豆包运行文件和 manifest 校验通过，代码改动被拒绝，CRLF 转换保留可信身份；运行层通过 macOS 和 Windows 交叉编译。原版文件夹内的上游测试文件也单独核验。
- 隔离完整应用通过 WorkBuddy 文件夹、豆包 ZIP 导入、独立源卡片、已有源拉取与勾选模型、Linux 桌面限制，以及 1280/1920/2560/3440 桌面布局检查。
- 真实界面完成多个网关 Key 自动生成、关闭后移除完整 Key、改名、停用/启用、独立轮换和删除；对应 `/v1/models` 200/401 验证通过，测试 Key 已全部删除。

## 待验收

- Android 实机触控与最终部署版本验收。
- WorkBuddy 真实账号登录后的供应商推理；当前没有供应商账号凭据，未将网关调用 Key 当作供应商凭据。
- 豆包工作的真实 macOS/Windows 应用启动、登录、模型菜单及云任务。当前节点为 Linux，没有可用兼容桌面节点；不能将导入、编译或命令构造通过记为真实豆包推理通过。

截图使用隔离节点，不包含生产源凭据。最终部署版本、真机记录和 PR 图片链接在发布验收后补充。
