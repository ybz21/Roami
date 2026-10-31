# 第二版设计原型验证

真实产品的首版实现、测试与真机验收另见 [implementation.md](implementation.md)。本文件保留原型阶段的历史证据。

2026-10-31。第一版的提案、独立 HTML 和验证已保留在 [2026-10-30 快照](records/2026-10-30/README.md)。当前记录只针对新版模拟原型，不代表统一模型网关已实现。

## 产物与复现

`README.md` 为当前 Product Design、User Stories 和 Technical Design；`index.html` 是可离线打开的独立原型。原稿与构建入口在 `assets/`。复用项目 `useLayout()`、SVG 图标、主题令牌和 antd，没有修改产品运行代码或全局翻译。

```bash
node docs/design/20261030-智能体模型切换/assets/build.mjs
frontend/node_modules/.bin/tsc -p docs/design/20261030-智能体模型切换/assets/tsconfig.json
node --check docs/design/20261030-智能体模型切换/assets/build.mjs
```

以上检查通过。需要先按仓库约定在 frontend 安装依赖。中文是内部设计稿的语言例外；产品接入时必须走全局中英 i18n。

## 桌面操作

通过 `roami chrome` 稳定标签 ID 验证：

- 添加模拟模型源、保存确认后可在来源目录中找到。
- 新建编程备用模型，保存草稿时未进入发布列表；发布后出现，并跳入该模型稳定 URL。
- Codex 在唯一智能体详情中选择使用 Roami 大模型并应用，出现默认配置更新反馈。
- 从 Codex 点管理来源与策略，进入编程主力；返回恢复原 Codex 详情，无第二份智能体表单。
- 主源未连上时，规则模拟选择 OpenRouter；已经输出时，模拟明确不自动换源或重放。
- 检查深色桌面与浅色窄屏；正常、来源失败、已有输出及配置冲突为页面内模拟状态。
- 浏览器资源记录无 `/api/` 请求，没有真实模型调用或配置写入。

320、390、820、1100、1280、1600、1920px 七档截图与 ResizeObserver 几何读取均无横向溢出，文档 scrollHeight 不超过视口高度。compact / medium / expanded / large 选择符合项目断点；内容在页面自己的容器中滚动。

## Android 真机

Redmi Note 8，物理屏幕 1080×2340、DPR 2.75、392 CSS px，Chrome 154，LAN 打开静态原型。

使用 `roami adb` 实际点按与滑动：

1. 从模型源切换到对外模型，打开编程主力详情，页面只保留一条返回栏。
2. 滑动详情容器，scrollTop 达约 321；文档 scrollTop 保持 0。系统返回回到对外模型列表。
3. 通过能力分类选择器切到唯一智能体目录，打开 Codex。
4. 选择使用 Roami 大模型，滑动至应用，点按应用和备份确认；读取到“Codex 默认模型已设为编程主力”的模拟成功反馈。
5. 上下栏保留，未增加第五个底部入口，所有读取的页面无横向溢出。

手机浏览器仍不提供 `roami chrome` 要求的 browser 实例 ID，因此 ADB 负责实际操作和截图，直接 CDP 只负责读取布局、定位和激活本任务页面。分类下拉打开后的选择在同一组操作中完成；不在中间重复激活页面，以免焦点变化关闭菜单。只操作本任务的页面 ID，未修改 CLI 的身份检查。

## 范围与清理

预览通过 `scripts/dev/isolated-roami.sh /tmp/roami-model-hub-v2 ...` 启动，结束时同一入口 `--stop` 清理。ADB 只移除本次创建的 19556 转发。

截图在 `/tmp/model-hub-v2-*.png`，不提交一次性图片到主分支；后续 PR 使用仓库 pr-shots 流程。设计链接和空白检查通过。

未修改 frontend/src、Go 或 Python，未运行与文档无关的产品全量测试。原型未实现真实鉴权、协议转换、主备、发布事务或安装；正式落地仍需 README 所列协议、CLI、事务、计量及前端门禁。
