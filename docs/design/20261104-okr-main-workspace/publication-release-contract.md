# 原成员发布交接契约

## Product Design

Main 批准内容后生成不可变交接，原成员继续同一任务执行。交接记录不是发送权限：当前账号、资源、原生执行身份及单次提交记录全部核对后才能进入发布。缺少通道时明确报告能力缺口，不再次生产相同内容。

## User Stories

- 制作任务进入下一轮后，仍可使用已经批准的原始内容字节。
- 后续限制、改稿、删除审核来源或更换实例后，旧交接不能继续发送。
- 同一业务键的未知结果只能对账，不因换工具调用或执行轮次而再次发送。

## Technical Design

`publication/releases.py` 组合已有 `AutomaticModeReview`、`approved_assets` 与 `publisher_identity`，使用项目范围的 `swarm_commands` 保存不可变交接，不新增数据库 schema。交接只选择已审核内容，不包含凭据，也不宣称账号已登录。

Main 准备交接前检查当前原目标、自动模式的真实用户来源、最新内容审核和实际冻结文件。保存前再次检查这些条件，避免异步读取期间失效。交接 ID 由规范化载荷摘要确定，相同输入返回同一回执。

执行端必须从宿主当前任务上下文取得 actor，而不是接受成员自报身份；核对实际 applied steer、原 task/run、当前目标和当前审核。接着由宿主的资源/账号适配器核验实际资源、当前账号、通道及所执行 Skill 的摘要。未接入适配器时禁止执行。再把此 admission 交给 `PostJournal`，保持先记录、单次提交及未知只读对账。

浏览器采用已有 task-owned resource、最新 observation 和 resource_actions。本地 Chrome 操作回执只能证明输入停止，不能作为平台发布事实；不信任成员任意指定的回执路径。原生 Skill、平台核验与专用事实验收接线完成前，不注册能宣称发布成功的工具。

## 验收

需要真实宿主 fixture 覆盖制作轮次推进、改稿和撤销、跨项目/成员/账号拒绝、旧 run 拒绝、源文件损坏、重试去重以及未知结果不重发。此工作树目前是实现候选，未注册生产入口、未部署、未产生平台回执。最终仍需原团队至少两轮真实闭环验收。

## 当前实现与剩余接线

`PublicationReleases` 已组合真实用户模式审核、内容审核、原任务实际续派身份与提交账本。`BrowserPublicationAdmission` 复用现有 ResourceLeases：检查原 run 的当前租约、暂停/接管、未结束操作、最新 observation 与平台 HTTPS 来源，再要求宿主账号探测回执绑定同一资源、观察和账号。路由证明同时绑定实际 Skill 摘要；成员自报或任意本地回执文件不作为输入。

预约最终提交应位于正文、媒体和 ALT 已准备完成之后，使用同一最新页面观察；页面变化时重新核对，不在已预约尝试上偷偷替换内容或账号。实际 UI 输入继续走已有 BrowserDriver 及 resource_actions。结果未知仍对账，不换业务键再次发送。

目前 17 项隔离专项通过，含真实续派/dispatch、单次提交与资源暂停、过期、页面变更、仿冒域名及缺少账号探测。宿主账号探测器、原 Skill 最终动作、平台事实核验和工具注册仍未完成，没有生产接线或真实发布声明。此浏览器实现不改变项目已有发布通道的选择；X 手机路径仍需对应设备适配与明确的现行范围。

## 2026-11-09：原生 CLI 接线修订

### 已核验事实与缺口

当前生产原 X 会话已通过 ADB 完成下一批三帖，原 B站会话已通过 Chrome 投稿 BV1cpWp6FE8f、BV1cnWp6hEZV、BV1wnWp6hEw5；Root 对公开来源独立核对作者和冻结文案。新结果仍主要保存在项目回执文件，不能反推它们已有宿主不可变版本、提交预约和独立事实验收。不得追溯伪造历史预约或审核记录；旧发布只按可核验历史事实导入，不能再授予一次提交资格。

### 沿用已跑通的发布路径

X 沿用原成员的 Android ADB Skill，B站沿用原成员的 Chrome Skill。自动化修复的范围是审核后交接、同一原成员执行、提交去重、结果恢复与后续取数，不重新建设发布渠道，不以 OAuth、平台 API 凭据或迁移受管浏览器作为前置条件。隔离测试中的受管 Browser Resource 不能替代这两条实际路径的验收。是否成功以平台结果及独立核验为准，不能把“交接已投递”写成“已发布”。

既有 `ProfessionalCapabilities` 已为实际原生成员签发 HMAC executionContext，限定 owner/taskId/runId/revision，调用时检查当前 CLI attempt、停止、steer、来源遗忘与时限。原生发布接线应复用该身份入口，不能让工具参数中的 task/run/session 声明充当身份，也不要求更换成嵌入式浏览器实例。现有 `BrowserPublicationAdmission` 仅覆盖受管 Browser Resource，不能冒称已覆盖直接 Chrome 或 Android 原生通道。

### 分层接口与模块边界

1. **Main 冻结与批准。** 保留 publication prepare/review。补齐 ALT 和音视频的不可变引用及关联审核：最终视频、音轨、字幕、封面、标题、简介、标签均由宿主保留字节。宿主按冻结视频提取审阅帧和实际音轨，绑定媒体 SHA、原节点 speech 参数所产转写及文本/图像上下文证据；成员自制报告不是宿主媒体审核证明。Main 实际看帧、读转写/字幕后批准，版本变化使旧批准失效。
2. **原成员交接。** Main 使用已批准版本创建 release，绑定原项目/团队/任务/成员和实际已应用 steer。原生调用复用宿主签发 executionContext；只增加明确的发布能力白名单，不将全部 Main 工具开放给原生成员。后续任务轮次可执行原审核字节，不修改原制作 attempt。
3. **通道适配。** 分为 `native_chrome` 与 `native_adb`，继续原项目 Skill、资源和账号。Chrome 使用稳定 browser/target 身份和既有 operationId/receipt-root；ADB 使用明确 serial、前台应用及原生账号核验。宿主适配器自己读取当前资源/账号状态并绑定原任务，不能接受成员给一个任意 JSON 文件就视为可信账号证明。账号 ID 始终是字符串。观察失效、资源变化或账号不符时先停止并重新核对，不切账号补救。
4. **最终动作与账本。** 文案、媒体、ALT/字幕等准备好之后，宿主核对 release 当前仍有效，先持久记录唯一 submitting 意图，再经该原通道执行一次固定最终动作；模型不能传任意 shell/JS/坐标作为“发布”。预填、上传与最终提交分开。持久化后失去响应即 unknown，重启或换 run 不返回第二次提交许可。主机现有 Chrome/ADB 输入工具仍可用于已授权的准备，正式提交走统一预约入口。
5. **事实核验。** 通道返回的状态页/平台 ID 是候选；固定平台的只读核验器保存原始响应，校验已批准账号、正文/简介与媒体关联。限定合法平台 ID，不开放任意 URL 或任意请求方法。平台 JPEG 转码不要求与原 PNG 字节相同；保留源媒体 SHA、上传/提交身份和公开媒体核验口径。审核中、已提交、公开和未知保持不同状态。
6. **专用验收与接续。** 外部发布不能通过放宽 swarm_verify 冒充文本任务成功。由专用事实验收消费可信发布账本/公开核验记录；成员自报不直接变成确认事实。原数据成员对实际新对象取数，Main 确认数据和看板，再复盘续派。历史已公开但缺宿主提交意图的内容，只能作为历史事实采集，不走“补提交”路径。

### 验收顺序

先用隔离 fixture 核验签名上下文、跨项目/账号/轮次拒绝、素材变更、单次提交与未知恢复，以及平台核验零 POST；使用可观测 fake Chrome/ADB 适配器证明预约在动作之前，并非 mock 返回成功就算上线。再在同一原项目、原 Main 和原成员完成至少两次真实循环，核对宿主记录、公开事实、新对象取数、确认看板、复盘与下一轮。此前的真实发帖/投稿保留，绝不为验证新接口重发旧内容。

本节中的原生最终动作仍是后续接线设计；候选目录已增加下述 Main 交接入口，但未部署，没有接管当前投稿、没有修改生产记录或账号权限。当前正在运行的原成员不因设计修订而停止。

### 原生最终提交执行层

`publication/native_submission.py` 组合现有 `PostJournal` 与宿主适配器：适配器先只读准备冻结载荷和当前场景；版本、账号、渠道及资源必须与交接一致。执行层等待 `post_submit` 事务持久化后，才调用适配器的固定 `submit_once`；随后保存平台 ID 候选，不把候选称为公开成功。断连、异常或缺少平台 ID 均保留提交意图，下一次调用被账本拒绝并要求对账。

新增三项回归使用真实任务续派、release admission 和 SQLite 账本，在 fake 原生适配器实际被调用时回读已提交的 intent，覆盖成功、响应断连和无平台 ID。与既有交接专项合计 20 项通过。此层尚未注册；Chrome/ADB 具体宿主适配器、平台只读对账和可信事实验收仍需接线，不能据此宣称自动循环已完成。

### B站原生投稿后的只读核验

`publication/bilibili_public.py` 只接受数字账号、合法 BVID 和 cid，固定 GET 官方 view 来源，禁用重定向，不需 OAuth。公开态必须同时命中 state=0、作者 UID、BVID、标题、简介和提交时绑定的 cid；仅允许已观察到的文末 LF 规范化。返回原始响应及其 SHA，不将封面转码或 cid 一致夸大成公开视频与源 MP4 的字节一致证明。审核中或首次 -404 只说明尚未确认，后续仍对同一 BVID 只读查询，不能再次投稿。

9 项专项覆盖正常、错作者、标题/简介/cid 变化、审核中、-404、重定向和非 JSON，全部只有一次 GET。已用实际原稿 BV1cpWp6FE8f 和冻结标题/简介/cid 成功只读核验，原始证据 `/tmp/okr-native-publication-integration-20261109/bili-native-real-readback.json`。这是对账模块实测，仍未注册为线上发布或任务验收工具。

`NativeReconciliation` 读取同一项目的 attempt、提交意图与平台 ID 候选，核对已持久化载荷的摘要、冻结版本/正文/媒体以及候选与提交内容的一致性，再调用宿主只读核验器。公开结果必须匹配渠道、账号和平台 ID，才保存 `publication_public_fact`。重复查询返回当时保存的事实，避免公开统计变化造成历史回执冲突；不会再次调用最终动作。结果未知且没有平台 ID 时，不从任意 URL 猜测或重发。

该连接层 8 项专项已通过，覆盖上述冲突、未知和项目所有者边界，并贯通真实 SQLite 账本、`NativeSubmission`、`BilibiliPublic` 与固定 GET 的 HTTP fixture。专项证明模块组合，不替代原生 CLI 注册、真实 Chrome/ADB 最终动作及连续运行验收。

### X 原生发帖后的只读核验

`publication/x_public.py` 使用已在真实项目验证的公开 syndication 来源，不走 OAuth API。账号和帖子 ID 保持字符串；正文按平台 UTF-16 展示范围读取，展开链接后与冻结正文比较，逐张核对 photo 类型、ALT 和冻结原图摘要。图片只从指定 HTTPS 平台 CDN 读取，禁用跳转；尺寸一致且 RGB RMSE <10、平均通道误差 <4 才记录像素比较通过，不宣称 PNG 与平台 JPEG 字节相等。此比较用于既定静态卡面；不支持视频或动图，也不把相近图片作为内容版权或来源证明。

10 项专项覆盖上述正常路径、错作者/正文/ALT/媒体、图片变化、UTF-16 范围错误、跳转、非平台图片 URL 与源文件变化，均只有 GET。已对真实帖子 2119534503328874878 成功核验数字账号、正文、ALT 和 1600×1000 原图，RGB RMSE 2.4496，证据 `/tmp/okr-native-publication-integration-20261109/x-native-real-readback.json`。仍需接通原生宿主最终动作与正式能力入口，不能把读取历史帖子写成新循环完成。

### Main 交接入口

候选目录注册 `swarm_publication_release`，Foundation CLI 对应 `roami swarm publication release --input JSON`，协调批次只允许当前项目、目标和所选原成员范围。参数关联 projectId/swarmId/delegationId/memberId/taskId、versionId/reviewId、channel/accountId；审核证明和实际原任务身份由宿主读取，不接受自报审核结果。该入口复用 `PublicationReleases.prepare`，返回 publicationAuthorized=false；原生成员最终动作仍需单独接线。

22 项交接专项通过，其中新增 5 项经实际 Foundation CLI 调用，覆盖当前 Main 成功、跨项目/成员/任务与账号拒绝。没有因此放宽 `swarm_verify` 对通用外部动作的限制，也未向原生成员开放 Main 的管理工具。
