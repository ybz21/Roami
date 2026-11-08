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

## 火山单 Key 接入（2026-11-08）

### Product Design / User Stories

火山识别服务只展示 API Key 输入框，明确默认使用豆包流式语音识别 2.0。用户无需填写 App ID、Access Token、资源 ID 或接口地址。原「模型」标签下的位置不变，原双凭据配置保留读取与执行兼容，填写 API Key 后优先使用新版协议。

### Technical Design

依据[新版实时识别参数](https://docs.volcengine.com/docs/doubao-voice/bidirectional-streaming-automatic-speech-recognition-websocket?lang=zh)、该页提供的官方 Go 协议示例，以及[流式识别接入说明](https://docs.volcengine.com/docs/doubao-voice/access-must-read-1-1?lang=zh)。

- API Key 路径默认连接 `wss://openspeech.bytedance.com/api/v3/sauc/bigmodel_async`，选择 `volc.seedasr.sauc.duration`，通过 `X-Api-Key` 鉴权，不发送旧鉴权头。旧录音文件识别的 endpoint/resourceId 自动使用新版默认值。
- `speech-volcano-stream.go` 封装初始化、gzip 二进制帧、序号和负序号尾包、响应解码、最终文本与服务错误。按 200ms 分包和发送，上传与接收并行，避免长录音阻塞。读取有大小与解压上限，HTTP 请求取消后关闭连接。
- 延续现有浏览器录完上传 16kHz/16bit/单声道 WAV 的交互，服务端再通过火山流式协议转写；此变更不代表浏览器已实现边录边上屏。超时覆盖录音时长与处理余量。
- `SpeechSettings` 隐藏旧字段并保留其数据，密钥和草稿仍使用原保存机制。

### Acceptance Evidence

本地 WebSocket 模拟覆盖单 Key 鉴权、2.0 模型默认值、完整录音分包、gzip、最终结果覆盖临时文本、错误帧、取消关闭连接、畸形帧和解压上限；race 检查通过。`backend/api` 与 `backend/server` 回归通过。前端覆盖只显示一个 Key 输入框、隐藏旧字段并保存后保留旧配置。未使用真实火山 Key 调用云端服务。日志：`/tmp/volcano-go-tests.log`、`/tmp/volcano-go-regression.log`、`/tmp/volcano-frontend-tests.log`、`/tmp/volcano-build.log`。

本次验证补充：Go 全量测试与 quick 门禁在隔离 tmux 服务内通过，未触发无关 Python 同步或运行时测试。前端原有 1565 项回归及新增单 Key 表单测试通过，typecheck、i18n、hover 和生产构建通过。桌面 1280/1920/2560/3440 均无横向溢出，中英文已核对；Redmi Note 8 经 LAN 的 HTTPS 服务显示仅 API Key 输入，ADB 上滑使页内 scrollTop 从 0 增至约 45，文档与视口同为 392 CSS px，上下导航及保存可见。截图：`/tmp/volcano-key-desktop.png`、`/tmp/volcano-key-phone.png`；新增 UI 测试日志：`/tmp/volcano-key-ui-test.log`；门禁日志：`/tmp/volcano-quality.log`。
