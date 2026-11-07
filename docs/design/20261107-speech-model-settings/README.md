# 语音识别配置归入大模型

## Product Design

将识别服务配置从「设置 / 语音输入」移至「能力 / 大模型」第一个「模型」标签的模型列表下方，作为「语音识别」区块，不单独占用标签。沿用页内滚动、表单宽度和移动端控件，不增加页面外框。识别服务可关闭，或配置 OpenAI 与 Volcano Engine。

「显示语音按钮」仍是个人偏好，归入「设置 / 会话与交互」。移除设置目录中的独立语音页；旧 `settings/node/speech` 与 `env/node/speech` 链接继续打开迁移后的配置页，保留现有节点参数处理。

## User Stories

- 管理模型时，可以在同一处配置语音识别服务、接口、凭据和模型。
- 已有用户直接读取原配置，无需重新填写；切换模型标签后可以恢复尚未保存的输入。
- 只想切换终端话筒显示的用户，可以在个人交互偏好中操作。
- 手机用户通过现有能力分类与标签访问配置，字段、保存和底部导航可触达。

## Technical Design

- `ModelHub.tsx` 在模型列表与使用情况下方复用 `SpeechSettings`，保留模型、用量与限额、模型定价三个标签。模型目录加载中或失败时仍可配置语音；旧 `speech` 子路由打开第一个模型标签。嵌入式新用户引导保持原模型配置范围。
- `speech-settings.tsx` 保持 `/speech/config` GET/PUT、原字段、默认值和 `speech` 草稿键，采用现有 `agent-settings-*` 表单样式及能力页的触屏下拉菜单。所有字段具有可访问名称，保存期间禁用编辑。
- `registry.tsx` 将 `voiceItem` 移入 `agent.new`，移除 `node.speech`；`route-hash.ts` 兼容旧链接。
- 新标签及提示同时提供中英文。服务商品牌名遵循现有专有名词例外。
- 后端、语音转写调用、配置文件格式均沿用现有实现。

## Acceptance Evidence

验证使用 `/tmp/roami-speech-acceptance` 的隔离服务与独立 tmux socket，不使用用户会话作测试夹具。测试语音配置仅在隔离目录落盘，未调用收费识别服务。

- 前端全量 Vitest：214 个文件、1565 项通过；覆盖配置保存、模型目录失败、草稿恢复、读取失败重试和旧路由。
- 最后一次触屏菜单样式调整后，相关 36 项测试再次通过。
- typecheck、i18n、hover 审计通过；quick 质量门禁通过。生产构建通过，仍有项目原有的大包体积提示。
- 桌面 1280、1920、2560、3440 CSS px：文档不横溢，表单在内容 pane 内，页面占满剩余宽高。中英文均核对。
- Redmi Note 8（Android Chrome，392 CSS px、coarse）：HTTPS 页能加载原服务设置；ADB 点按切换到 OpenAI，保存后 GET 返回原 App ID 与新服务选择；真实上滑后页内 scrollTop 从 0 增至约 82，文档宽度保持 392。顶部能力栏和底部导航可见。

本地截图与日志（一次性产物不提交进主分支）：

- `/tmp/speech-settings-before-desktop.png`
- `/tmp/speech-settings-desktop-{1280,1920,2560,3440}.png`
- `/tmp/speech-settings-after-en.png`
- `/tmp/speech-settings-after-phone.png`
- `/tmp/speech-all-tests.log`
- `/tmp/speech-quality.log`

## 位置调整

根据后续反馈，语音识别改为第一个「模型」标签下的区块，去掉独立标签。补充验收截图使用 `/tmp/speech-inline-desktop.png` 与 `/tmp/speech-inline-phone.png`；测试和构建日志使用 `/tmp/speech-inline-tests.log`、`/tmp/speech-inline-build.log`。

本次位置调整重新通过全部 214 个文件、1565 项前端测试及 typecheck、i18n、hover、build、quick 门禁。桌面四档宽度无横向溢出，模型编辑面板可开关；中英文均核对。Android LAN 页面确认模型列表下方出现语音区块；为避开同机其他实例的 Cookie 覆盖，后续触控通过 ADB 反向转发使用独立 localhost 域名。ADB 上滑后该页 scrollTop 从 0 增至 316，文档与视口均为 392 CSS px。手机截图通过选定的真机 Chrome 标签采集，避免其他任务切换前台干扰截图。
