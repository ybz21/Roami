# 思考强度与分类能力目录

## 思考强度

输入栏在模型名旁显示实际思考强度；点模型菜单 → 思考强度切换。设置 → 智能体 → 模型与连接分别配置 Main / 后台智能体。两处使用同一持久化接口，不重复保存 Base URL / Key。

- 保存到节点私有 `model-settings.json`，页面重载与服务重启后保持。
- `reasoningEffort: null` 表示模型默认：移除显式 `reasoning_effort`，不把 null 发给供应商。
- 改动合入现有参数，其余生成参数保留；Main / Worker 分别配置，参数参与供应商缓存身份。
- 更换模型或服务连接会清除旧强度，避免把旧模型档位带到新模型；可在同次保存显式指定新值。
- 已知模型按档位过滤并校验；未识别模型列出兼容协议通用档位，供应商不一定接受全部值。当前配置 GLM-5.3-Flash 的选择为默认、low、high、max。
- 正在运行时沿用配置更新的忙碌保护，失败保留原值并展示错误，不虚报已切换。

档位依据：[OpenAI 官方文档](https://developers.openai.com/api/docs/guides/deployment-checklist#set-up-reasoningeffort)、[Z.ai 官方模型文档](https://github.com/zai-org/GLM-5/blob/main/README.md)。供应商支持与应用自身的兼容代理分开判断，本轮没有迁移模型或更换传输协议。

## tool_list

常驻工具由 `tool_search` 更名为 `tool_list`，删除旧注册，不保留别名。CLI 同步改为 `roami agent capability list`，移除 `capability search`。历史消息及既有审计记录保留原名，不据此重新开放旧执行入口。

无参数即可列出全部分类的第一页，`kind` / `query` / 分页参数均可选：

```json
{}
```

CLI 可直接运行 `roami agent capability list`。需要分类时再传参：

```json
{"kind":"skill"}
```

支持 `kind: all | mcp | skill | cli`、可选 `query`、`limit`（默认 10、上限 20）和 `offset`。返回 `items / total / offset / nextOffset / totals / catalogVersion / truncated`，有缺失匹配时返回建议。MCP 单独分类，仍按当前角色、节点、启用状态过滤；人类管理 CLI 可查看后台目录，不扩展模型执行权限。

Main 保留 read / bash / edit / write / tool_list / delegate / ask_user；普通 Worker 5 个，研究 Worker 3 个。命令执行继续走 bash 与受管 Roami CLI。

截图中的 browser_open / browser_observe / browser_act 是 CLI 能力内部名称，底层为 BrowserDriver → `roami chrome`。在“能力管理 / CLI / 浏览器”查看，不重新加入核心工具列表；skill_read 同样是 read 技能后内部操作的名称。

## 验证

- `scripts/dev/quality/check.sh full`：Go、Ruff、Python 536 项、TypeScript、i18n 2894 keys、hover、生产构建及密钥扫描通过；完整前端 Vitest 92 文件 / 665 项通过。
- 独立实例实际 CLI：无参数 `capability list`、MCP / Skill / CLI 分类、可选关键词、分页、浏览器三项操作通过；旧 `capability search` 返回退出码 2。
- 模型工具回归：无参数 `tool_list({})` 走默认 all 分类 / 10 条分页；显式分类、分页、MCP 角色限制和禁用策略通过。旧工具执行返回 TOOL_UNAVAILABLE。
- 桌面与真实 Redmi Note 8：真实触控打开模型菜单、切换强度、刷新保持、清除到模型默认、设置页独立保存 Main / Worker；能力管理仅有 tool_list，CLI 分类显示三项 Browser 操作；无文档横向溢出。英文菜单验证通过。
- 用户既有网关 / GLM-5.3-Flash 实际请求：high 强度回复完成；随后真实模型依次调用 tool_list(kind=skill，无 query) → skill_read(roami-dispatch) → skill_read(projects-sessions)，给出 project sessions 命令。三次工具均 succeeded，没有新建业务任务。两轮总计 36.84 秒，属于连通性与链路验收，不代表延迟目标已完成。
- 发送到供应商的 reasoning_effort、恢复默认后字段缺省、Main / Worker 隔离及其他生成参数保留，另由 MockTransport 请求断言覆盖。实际请求通过不等于供应商一定采用相同内部思考预算。
- 自动脚本初次遇到异步轮询 / 保存完成等待与本地化标签选择器问题，校正脚本后完成全流程；没有用旧界面或只读 API 代替手机触控验收。

本轮未把股票查询截图中的全部研究失败当作已修复，未修改既有研究任务、生产会话或私有连接凭据。MCP 实例未配置远端连接（目录 0 项），外部 MCP 分类与权限由集成夹具验证。

## 截图

![桌面改前](https://raw.githubusercontent.com/ybz21/Roami/pr-shots/pr-329/roami-effort-before-desktop.png)
![桌面改后](https://raw.githubusercontent.com/ybz21/Roami/pr-shots/pr-329/roami-effort-after-desktop.png)
![手机改前](https://raw.githubusercontent.com/ybz21/Roami/pr-shots/pr-329/roami-effort-before-phone.png)
![手机改后](https://raw.githubusercontent.com/ybz21/Roami/pr-shots/pr-329/roami-effort-after-phone.png)
![工具目录](https://raw.githubusercontent.com/ybz21/Roami/pr-shots/pr-329/roami-tool-list-phone.png)
![浏览器属于 CLI](https://raw.githubusercontent.com/ybz21/Roami/pr-shots/pr-329/roami-browser-cli-phone.png)
