# 长项目上下文与证据分页

关联 #829，复现为单行 JSON 174369 字节，默认行读取仅返回 50000 字节，truncated=true、nextOffset=null，模型无法继续取得后面的 daily Skill。

## 产品设计与用户故事

Main 可以完整读取项目上下文与成员证据，长行和中文不能让它误认为读完。部分读取不能通过独立验收。无需用户换文件格式。

## 技术设计

保留既有行/字节参数语义，不把 nextOffset 的单位偷偷切换。每次返回 paginationUnit、hasMore 和 nextRead。长行预览仍标 truncated，nextRead 指向同一 artifact 的 offset=0 / limit=16000，从头按字节读取；后续保持 limit=16000，避免再次进入兼容行分页分支。回读未变更、未遗忘和归属检查仍复用原路径。

字节页只在完整 UTF-8 码点处结束，nextOffset 依据实际返回字节推进，不用替换字符破坏原文。过小页无法容纳第一个字符时明确报 ARTIFACT_TEXT_LIMIT_TOO_SMALL；无效 UTF-8 以 base64 标注且 textAvailable=false，不当文本审核证据。

从发布文本审核提取现有 artifact_text_coverage，并供 Swarm 验收共用。只有当前真实成功工具读取页连续覆盖完整原文、长度和 SHA 全部匹配才算读完；长行预览、缺页、伪造回执和旧回合仍不能通过。

## 验收

真实 Runtime/Gateway 中放入超长中文 JSON，首个预览验收失败；按 nextRead 完整读取，不出现替换字符，拼接逐字节等于原件，最后受管验收通过。复用已有跨任务、旧回合、遗忘和发布文本完整性回归。
