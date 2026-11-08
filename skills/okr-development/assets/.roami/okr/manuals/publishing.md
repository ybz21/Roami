# 发布操作

先读项目已验证的发布流程与历史回执，确认该渠道实际用的是 API/MCP、浏览器还是手机。能力目录中没有 API 不能证明没有发布方式。新接口开发不自动废止既有可用流程。

Main 独立审核当前版本后，在已授权账号与自动模式范围内续派原成员。核对真实登录账号、正文、媒体/ALT和冻结清单，每条单次提交，取得平台 ID 和公开回读后才记为发布。结果未知先对账，不换键重发。

临时验收的“只读、不发帖、不触设备”只约束该次验收，不能直接写成所有后续运营的永久限制。仍然有效的用户设备/账号边界必须遵守；与旧流程冲突时向用户澄清具体范围，不能偷偷绕过，也不能永久逐条重复报批。

项目实际采用的通道、账号核对步骤、设备独占方式、素材输入、提交/公开回执、失败恢复和历史成功样例，由 Main 在此补充。不要放密码、Cookie 或 Token；不要声称模板已连通账号。

新物料按 materials/YYYY-MM-DD/<渠道或工作类型>/<简短主题>/ 保存，任务与运行身份记录在清单。旧路径和正在执行的任务保留。

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
