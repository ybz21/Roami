# 发布操作

先读项目已验证的发布流程与历史回执，确认该渠道实际用的是 API/MCP、浏览器还是手机。能力目录中没有 API 不能证明没有发布方式。新接口开发不自动废止既有可用流程。

Main 独立审核当前版本后，在已授权账号与自动模式范围内续派原成员。核对真实登录账号、正文、媒体/ALT和冻结清单，每条单次提交，取得平台 ID 和公开回读后才记为发布。结果未知先对账，不换键重发。

临时验收的“只读、不发帖、不触设备”只约束该次验收，不能直接写成所有后续运营的永久限制。仍然有效的用户设备/账号边界必须遵守；与旧流程冲突时向用户澄清具体范围，不能偷偷绕过，也不能永久逐条重复报批。

项目实际采用的通道、账号核对步骤、设备独占方式、素材输入、提交/公开回执、失败恢复和历史成功样例，由 Main 在此补充。不要放密码、Cookie 或 Token；不要声称模板已连通账号。

新物料按 materials/YYYY-MM-DD/<渠道或工作类型>/<简短主题>/ 保存，任务与运行身份记录在清单。保留旧文件及当前正在执行这一轮的路径；同一长期任务的后续新轮次也使用可读目录，不把“保留当前轮次”理解为永久沿用 UID 层级。

## 宿主准备清单：准确格式与顺序

制作任务的通用物料 manifest 不能直接当作发布准备清单。宿主要求顶层 `identity` 对象，包含来自当前真实任务的 `taskId`、整数 `revision`、`runId`；`files` 每一项直接包含这三个身份字段以及 `path`、正整数 `bytes`、完整小写 SHA256，仅有每项嵌套的 identity 不够。不要从旧轮次猜身份，也不把顶层三个字段当成 `identity` 对象。

清单与待冻结的正文、图片放在同一主题目录。`files[].path` 相对 **manifest.json 所在目录**，不是项目根或执行目录。例如 manifest 在 `publication-input/manifest.json`、正文在同目录时，path 为 `01-post.en.txt`，不能再加 `publication-input/`。清单字段可按以下 Python 结构生成；`scope` 必须来自宿主当前任务，`root` 是实际清单目录：

```python
import hashlib
import json

identity = {key: scope[key] for key in ("taskId", "revision", "runId")}
assert type(identity["revision"]) is int and identity["revision"] > 0
files = []
for relative in selected_paths:
    payload = (root / relative).read_bytes()
    files.append({**identity, "path": relative, "bytes": len(payload),
                  "sha256": hashlib.sha256(payload).hexdigest()})
manifest = {"identity": identity, "files": files}
(root / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2))
```

这只是格式，不授予读写任意文件的权限。路径保持在本次已分配目录，不能越界、用隐藏路径或把不可见文件塞进清单。已有受管文件不要被未分配的外部写入者覆盖；在原任务中续派必要修正。

Main 的顺序是：读取当前任务与真实完成回执 → 通过 `read artifact://ID`（实际为 `artifact_read`）完整读取所选的宿主留存文本产物，再读取正文/ALT及当前图片（图片需实际视觉输入）→ 用 `swarm_verify` 验收制作/输入任务 → `swarm_publication_prepare` 冻结 → 读取返回的冻结内容 → `swarm_publication_review`。只看旧轮次图片、成员报告或 hash 字符串不足以通过 `SWARM_ARTIFACT_REVIEW_REQUIRED`。制作验收与发布审批分开，验收制作绝不等于已发布。

prepare 的 `manifest.id` 必须是本轮结果中宿主留存的 artifact ID，不是文件名；`content.body`/`content.images` 必须逐字等于清单的相对 path。业务键对应真实计划发布条目，跨修正与重试保留。`PUBLICATION_AUTHOR_NOT_CURRENT` 先核对是否已验收、是否仍为当前任务及运行；`INVALID_PUBLICATION_MANIFEST` 核对上述结构和路径，均不能改称账号授权失败。

`accountIdentity` 是有独立证据的平台数字账号 ID 字符串，不是 `@账号名`、昵称或主页网址。例如格式为 `"123456789"`，这里只示范格式，不能把示例 ID 用于真实账号。遇到 `INVALID_PUBLICATION_ACCOUNT_ID` 时保留原业务键、账号及已验收作者，从可信证据核对数字 ID；无法核对就如实停在该缺口，不猜 ID、不换账号。历史账号 ID 只说明身份对应，不能证明当前登录、投稿权限或发布成功；冻结版本也不授予发布权限。

验收所选文本产物必须逐份通过 `read artifact://ID` 读取完整、不截断的留存字节；大文件按工具返回的分页继续读完，并在后续 assistant 消息调用 verify。`file_read /磁盘路径`、artifact 的元数据、状态汇总或另外一份同 SHA 文件，都不替代这份宿主留存读取回执。不要清空 artifactIds 尝试绕过验收。


## 图片 ALT 与批准版本

支持 imageAlts 的宿主上，prepare 的 content.imageAlts 是相对清单目录的 ALT 文本文件路径数组，按相同位置对应 content.images；每张图片恰好一个 ALT。例如 images=["card.png"]、imageAlts=["card-alt.txt"]，两份文件都在清单 files 内，不把 ALT 原文直接填进路径。Main 完整读取返回的冻结正文及 ALT，并实际查看对应图片后再 review。改变 ALT 必须重新 prepare 和 review，沿用原业务键；旧版本不包含的侧车文本不能假称已获批准。宿主尚未声明该字段时只保留候选，不探测生产写入口。冻结和内容审核仍不等于发送权限或平台发布。

## Main 工具与原生成员能力

Main 的 prepare/review 目录只描述 Main 当前回合可调用的发布管理操作，不代表 Codex、Claude 等原生成员的全部 CLI 能力。先核对原项目历史成功回执、当前本轮任务范围，以及成员实际可用的 Skill/CLI；不能仅因没有专用发送工具，就认定必须新增 OAuth/API 或重新制作内容。

- 原任务是“只改清单、不发布”时，成员必须停在该范围。审核完成后，Main 通过受管 task_steer 给同一成员、同一任务追加有边界的发布工作，并核对真实新 revision/run 和原 provider 会话。不要把制作轮次直接当发布轮次。
- 发布前读原通道 Skill，核对实际账号、当前内容/媒体/ALT 字节与稳定业务键。命令存在、历史成功和公开作者身份均不证明当前设备、登录或权限可用。
- prepare/review 返回 publicationAuthorized=false 表示这项管理操作没有授予发送权限；用户原有的明确执行授权需要单独核对，不能把该字段当成所有原生通道均不存在。现行手机、人工账号页限制和宿主要求的检查仍有效，禁止借 CLI 绕过。
- 只在已明确允许的资源与账号范围内按原 Skill 单次执行。先保存本次意图与业务身份，已有未知尝试先对账；保持真实上传、提交和公开状态分开。没有平台回执就如实报告未确认。
- 原生 CLI 操作成功不等于宿主已接受平台事实。当前 swarm_verify 拒绝通用 external_action；自动验收需要专用的可信平台核验接线，不能自报 consent 或修改任务状态绕过。该缺口与“没有执行命令”分别报告。

## 最终成片的音轨审计

转写输入来自实际待发布 MP4 的最终音轨，不拿配音稿、SRT 或重生成的音频代替。保留源 MP4 摘要、提取命令、ffprobe 和输出摘要。现有语音服务需要 WAV 时，可用 `ffmpeg -i FINAL.mp4 -map 0:a:0 -ac 1 -ar 16000 -c:a pcm_s16le FINAL.wav` 转换格式，不额外归一音量、降噪或变速；先确定新的输出路径，不能覆盖既有证据。

具备本轮原生 CLI 权限的原成员先读 `roami speech help`，再用实际选项 `roami speech transcribe --file WAV --file-root AUDIT_DIRECTORY --expected-file-sha256 WAV_SHA --json`。它复用节点已保存的登录和已配置语音服务，保留原始响应、输入摘要与转写全文，不复制 cookie、不改 provider/model/key。Main 的受管目录若没有该能力，交给原来具备原生 CLI 的成员；不能套 Shell 绕过受管拒绝。失败保留原响应，不把匿名 401 当作语音服务不可用，不重复盲试。

Main 独立读取原始转写，对照最终音轨身份、SRT 句序与画面后决定。机器转写及字符相似度不等于人工听审或内容批准；品牌拼写、术语大小写与同音识别差异要逐项说明，不靠相似度阈值自动放行。审核通过后沿用已核验的原生 Chrome/ADB 路径，内容决定、实际提交与平台公开仍分别留证。

## 真实时刻与日汇总

审核、提交与公开时刻优先来自宿主或平台回执。自写记录先读取真实时钟；未知保持未知，不猜整点或未来时刻。已引用记录的时刻有误时保留原件及冻结输入，另追加更正，关联原回执和实际宿主动作；不因此换业务键、重发或覆盖原始证据。

“本成员本轮未发布”不能写成“整个项目本日未发布”；“本轮未启用日程”不代表项目既有日程关闭。日 README 分渠道记录真实回执，区分成员行为、项目当前状态与采样时刻。日索引是检索产物，不能替代公开证据，也不应阻塞证据已充分核验的投稿、取数或独立验收。
