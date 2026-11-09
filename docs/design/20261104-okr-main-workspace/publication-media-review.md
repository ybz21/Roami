# 冻结音视频的关联审核

关联 #761；承接 [原生发布交接](publication-release-contract.md) 和 [机制原型](publication-media-review.html)。当前是实现前设计，未注册、未部署。既有 Chrome/ADB 路径继续运行。

## Product Design

用户仍只与原 Main 对话。原成员交付后，Main 审核当前版本，再交原成员执行；不增加发布面板或逐条人工审批。宿主提供能追溯到冻结视频的画面、实际音轨和转写，避免把成员自己生成的报告当作宿主观察。审核通过仍不代表发送或公开。

## User Stories

- Main 看到宿主从当前视频提取的画面，并读取实际音轨的转写、原字幕和来源后，批准准确版本。
- 原成员换稿、目标撤销、源被遗忘或 Main 租约变化时，不沿用旧审核。
- 模型没有收到图片、转写服务失败或证据不全时，保留素材并给出具体缺口，不虚报看过或听过。
- 重复读取沿用该版本已保留的检查结果；不重新制作、不重新发布，也不把转写缓存说成本次新执行。

## Technical Design

### 输入与生成

复用 publication prepare/review 的冻结版本、原 Main/成员/task/revision/run 和现有 artifact 存储。仅接受当前版本内的 video/audio 引用；模型不能传任意文件、URL、脚本或 ffmpeg 参数。检查每次 I/O 前后的目标、租约、版本及原字节 SHA。

视频使用宿主固定 ffprobe/ffmpeg 参数探测并抽取，不执行项目脚本；限制解复用格式与协议，禁止媒体引用其他本地文件或网络。均匀覆盖完整时间轴，保留实际抽样口径与请求时间点，生成 18 帧、3 张接触表，允许 Main 按索引另读原帧核对。接触表是抽样观察，不声称逐帧连续观看。使用现有 Main 图片预算；不能容纳全部必需图像时拒绝批准，不静默丢图。

音轨必须从最终冻结 MP4 提取，不能以作者另给的 WAV 替代；若同时选了独立 audio，也分别检查。通过既有 `roami speech transcribe --file --file-root --expected-file-sha256 --json` 调当前节点已保存的语音服务，不硬编码服务商或模型，不修改路由/费用/用户环境。保存实际音轨 SHA、转写调用结果及原始文本来源。没有音轨与转写失败分开记录；不能把失败当作静音。静音素材的批准仍由 Main 按本项目要求判断，不声称已听审。

产物写宿主私有 artifact 存储，不写入成员正在使用的工作目录。报告中的长文本分块保留原始内容与顺序，避免 #829 的单行截断；保留原始转写摘要及完整字节 SHA，不能用摘要替代实际读取。

### Main 工具与真实模型输入

仅增加一个绑定 Main 的 `swarm_publication_media`，操作为 inspect/image。inspect 返回当前版本的报告、转写与画面引用；image 只读取该报告内的接触表/帧，输出当前 Main 回合的认证图像快照。Foundation 别名仍走注册目录，不新增用户界面入口。

接触表进入与现有 Main 图片共用的输入准备流程，保留工具回执、artifact SHA、Main turn/lease、版本及原媒体 SHA。扩展现有图片来源选择器，按读取顺序选图，避免旧文件图片挤掉新媒体图。不能只在 JSON 里写 image=true 或虚构 prompt manifest。

批准时同时要求：原冻结文本/字幕、宿主报告/转写真实进入当前模型输入；所需接触表实际出现在当前 prompt manifest；源媒体与派生资料均仍可读取且 SHA 一致。每个版本立即读取并审核，再处理下一版本；整批全部通过后才续派原作者。任一来源变化都拒绝批准。

### 持久化与隔离

复用 swarm_commands 保存版本范围的完整检查回执，artifact 元数据保存派生关系，不新增发布许可或假造 post_submit。并发 inspect 以 owner/version 互斥，完成结果幂等；未完成或失败不写成成功。原节点服务故障保留错误，可恢复的只读重试与外部发布重试分开。

派生帧/转写依赖原媒体及原清单。任何原件删除、purge 或被遗忘后，派生资料也不能继续被普通 artifact 读取绕过；当前 Main、项目、目标、最新版本与租约边界继续核验。正常撤销保留历史事实，但不允许新审核。

### 代码边界

- dispatch/publication_media.py：原目标/Main/作者/最新版本在 I/O 前后复核；后续接入派生证据持久化。
- publication/media_inspection.py：不可变源文件检查、接触表与解码编排。
- publication/media_decode.py：固定探测、抽帧与音轨；无任意命令接口。
- publication/media_transcription.py：调用现有节点语音 CLI，保留实际来源，不覆盖配置。
- tools/publication_media_catalog.py：Main 绑定 inspect/image 入口。
- context/main_media_images.py 与 chat_images.py：认证派生图片进入真实模型输入。
- storage/publication_media_evidence.py：版本关联、读取证明和最终事务复核；artifact_store.py 保护派生来源遗忘。
- dispatch/publication_review.py：仅在上述证据充分时解除音视频 unavailable；保留原文本/图片条件。

## Acceptance

先验证真实注册工具与 Agent 输入链：缺转写、仅作者报告、图片未进模型、改稿、跨项目/成员、旧租约、撤销/遗忘、重复调用与处理中断均不能假批准；普通图片审核保持原行为。实际 ffmpeg 使用自建短片和已公开素材做只读验证，语音调用沿用当前节点配置，不伪造 Main 审核。

再由原 Main 处理新一轮原成员交付，观察宿主提取、实际输入与批准记录；最后仍须接上统一提交意图、原 Chrome/ADB 最终动作和平台对账。当前 2026-11-09 三条真实 B站新稿已公开且原 Main 后续正式验收成功，这是既有路径的运行证据，不追溯制造其宿主媒体审核或提交意图。

## 现有链路实证与实现边界（2026-11-09）

只读检查真实 B站制作审核回合：21 次 prompt manifest 包含 imageEvidence，最新一轮包含 6 张真实 workspace_file 图片，能与同回合成功 file_read 的路径、toolCallId 和 SHA 对应。记录在 `/tmp/okr-loop-release-7c5b8a8f-20261109/bili20-main-image-input-audit.json`。这证明既有 Main 图像输入可复用，不需要再造对话渲染或视觉模型通路。

该记录只证明图像送入模型，不证明整段视频或最终音轨已核验。后续实现聚焦冻结视频的宿主取帧、最终音轨转写和派生证据失效关联；仍复用已有 model capabilities、图像数量限制和保存的语音配置，不能借此重建 Chrome/ADB 发布路径或覆盖原团队身份。

## 解码参数依据

实现使用固定的 `format_whitelist` / `protocol_whitelist`，并对 MP4/MOV 显式保持 `enable_drefs=0`、`use_absolute_path=0`，不把清单、URL 或外部引用交给自动探测。依据 [FFmpeg 格式文档](https://ffmpeg.org/ffmpeg-formats.html#mov_002fmp4_002f3gp) 和 [协议文档](https://ffmpeg.org/ffmpeg-protocols.html#Protocol-Options)。本机隔离工具链 FFmpeg 6.1.1 的 `ffprobe -h demuxer=mov` 已确认两个选项存在且默认关闭；这是实现参数核对，不代表音视频审核工具已经实现或上线。

## 当前实现状态（开发源码已注册，未部署）

| 部分 | 当前状态 |
| --- | --- |
| `publication/media_decode.py` | 固定本机 MP4/WAV 解码，关闭外部轨道，遇解码错误退出，限制输出，取消时停止实际子进程 |
| `publication/media_inspection.py` | 校验源文件 SHA 与身份前后不变，18 个均匀请求位置、3 张接触表和完整最终音轨；抽样不声称完整观看 |
| 离线回归 | 当前媒体专项及既有 approved-assets 回归101项通过；此前 artifact 存储、原 Main 图片、文本审核与协调工具联合179项通过；含真实小型 MP4 取帧/取音轨、缺帧、源变更、无效音轨、子进程取消，以及真实宿主数据库上的跨 Main、旧租约、非媒体文件、解码期间撤销/作者推进/原件删除 |
| 原 Main 图片输入 | 既有生产能力已核验；新增 publication_media 输入类型在隔离注册 CLI 回执中送入真实 image_url 输入，5项正反回归通过，尚未生产验收 |
| 当前目标/租约/作者绑定 | `dispatch/publication_media.py` 已复用 current_version 在文件校验和解码前后检查；开发源码已注册 Main-only inspect/image 工具并保存派生资料，尚未部署 |
| 保存配置的语音转写 | `publication/media_transcription.py` 已调用原 Node CLI，校验音轨 SHA/字节、HTTP状态、完整响应 SHA 与一致的转写正文；失败不重试。已复用项目隔离的 intent/result 不可变回执，覆盖并发、中断和重入，已接入开发工具、真实模型图片输入与最终批准证据检查；仍未部署 |
| 原片删除/遗忘后的派生产物失效 | 已加入 publication_media 来源约束：注册与普通 get/read/read_page/verified_path 校验原片/原清单删除、purge及遗忘；I/O 后复核。正式审核与发布交接均检查派生来源；仍未部署 |
| 独立 Main 审核与最终批准 | 开发源码已接入：完整报告/转写读取、实际模型像素输入及最终事务复核；纯音频、无音轨视频、空转写与证据删除回归通过，线上尚未启用 |

这批底层代码不在当前每日执行恢复提交 `448861af` 中。后续必须完成持久转写回执、工具接入和真实模型图像/文字输入的联合验证后，再改变媒体审核可用性。

依赖边界：已从 Ubuntu apt 已校验摘要的 ffmpeg 包安装用户级 ffprobe，保留原 ffmpeg 和保存环境不变。默认运行时发现实际工具，3秒视频/2.4秒音轨的真实烟测成功输出18帧、3张接触表和2.414875秒PCM，证明按音轨而非视频总时长核对。烟测不使用 `/tmp` 工具路径；新工具代码仍未部署。语音回归使用隔离 CLI fixture，真实项目既有语音调用与此新宿主路径分别验收；不修改保存的模型/语音路由。

转写未知结果：超时返回 `PUBLICATION_MEDIA_TRANSCRIPTION_OUTCOME_UNKNOWN`，不重新提交音轨。已加入按冻结版本和最终音轨摘要的持久 intent/result；尚需真实工具与最终批准联合验证，不能仅凭局部回归宣称已上线。当前只注册于开发源码、尚未部署，因此没有对线上提交或语音配置造成影响。

### 派生资料的存储与失效

接触表、最终音轨、转写和报告沿用现有 artifact 存储。宿主专用 metadata.kind=publication_media、mediaSource={versionId,artifactId,sha256} 关联不可变原版，不复制或伪造原作者 deliverable 身份。注册事务和普通 get/read/read_page/verified_path 均校验来源：原件必须属于同一 owner、确实是版本选定的音视频、未删除/purge/被遗忘；若原件从原清单冻结，还要检查原清单仍有效。派生物不能反过来成为原件。I/O 后再次核验，避免读取期间撤销来源仍返回派生内容。此关联只证明来源有效，不代表 Main 已读、已批准或拥有发布权限。

### 转写回执与中断恢复

复用现有项目隔离的 `swarm_commands` 不可变操作日志，不引入新数据库或迁移。请求身份由冻结 versionId、sourceArtifactId/sourceSha256、宿主从最终音轨提取出的 audioSha256 组成。第一笔事务提交唯一 intent；随后仅该新 intent 调用一次现有 Node 语音入口。完成后追加独立 result 回执，保存关联的宿主转写原始响应与纯文字 artifact 引用。结果不写明文到操作日志，来源删除/遗忘约束继续生效。

重入先读同一 intent/result：成功则验证已留存响应与音轨摘要后复用；已有 intent 却无成功结果时报告执行中/结果未知，不能重复上传，不能通过换操作ID绕过。超时、取消或收到不可核验响应保留未知结果。外部调用完成后，即使目标被撤销也保留实际结果事实，但当前 Main/版本校验失败时不能返回审核资格。读取转写、把图片和全文送入真实模型以及最终批准仍另行证明。

主线同步：已将开发工作区同步到 `77f006ca`，未提交原件保存在 `cdca67b8` stash 与 `/tmp/okr-media-rebase-20261109/before-source.tar.gz`；保留全部新模块与测试，合并了主线已有的分页、持续接续和日期统计文档入口。新媒体普通读入口仅接受同一 Main 当前回合真实 inspect 结果中返回的引用；图片另经成功 image 回执进入模型输入，不冒充 workspace_file 来源。

### 最终批准证据接线

开发源码的 `swarm_publication_review` 现按以下完整证据放行；当前线上版本尚未包含本改动：从当前回合成功 inspect 的真实结果取快照，核对 report 与实际接触表/最终音轨哈希；有音轨时核对项目隔离的 intent/result、原始语音响应与转写一致性。Main 必须完整读取 report 和 transcript.json，后者为 {text: 字符串}，即使无识别文字也能明确读到空字符串而不是零字节假终点。原始语音响应由宿主验证，不要求把同一段长 JSON 再灌入模型。

每张接触表必须存在本回合成功 image 工具回执、实际最新 Main prompt_manifest 中 publication_media 类型的像素证据，以及早于当前批准 assistant 的对应工具结果。源版本、作者轮次/运行、Main 租约与完整文本读取证明继续使用已有检查。文件/文本/图像核验后，在最终保存事务再次复核当前冻结版、派生来源、原始媒体/清单存活、转写结果与最新图像证据；任何改变均拒绝，不以开发工具已注册代替这些条件。


### 发布交接与原通道

Main 批准后，原作者可推进到发布轮次；不可要求他永远停在制作 revision。`publication/approved_assets.py` 保留冻结作者身份和审核来源，额外校验报告、接触表、最终音轨及转写仍存在且未删除/遗忘。`publication/releases.py` 在交接前核验这些实际文件的字节，不更改原业务键或提交意图。最终事务遇到证据删除、Main 租约改变时拒绝批准，不把旧缓存当有效审核。

发布仍复用原团队的 Chrome / ADB。媒体检查工具不是新发布渠道，不向平台提交内容，也不替代账号、内容及单次提交核对。用户授权的原生流程可继续运行，不能把开发加固尚未部署当作原渠道不存在。

开发验收：`test_publication_media_review.py` 与既有 approved-assets 回归19项通过；新增纯音频/无音轨视频与最终事务竞态后，媒体审核专项14项通过。全量门禁与实际 Main 上线验收另记，不将隔离语音 fixture 当成真实服务调用。

完整音轨约束：FFprobe 提供音轨本身时长，FFmpeg 使用 `-xerror`，输出 WAV 必须实际解析为单声道 PCM16/16000Hz。读取实际 PCM 帧数，要求与源音轨时长相差不超过0.1秒；不使用视频总时长替代音轨时长，不信任 streaming WAV 的占位长度或只有 RIFF/WAVE 文件头。缺失时长或截短音轨拒绝审核。
