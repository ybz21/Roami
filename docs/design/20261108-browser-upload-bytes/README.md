# 文件选择后的异步读取

## Product Design

文件已选入网页不等于页面已读取或上传。当前上传入口在选择结束后清理私有临时副本；B站随后读取 File 出现 NotFoundError，上传停在 0%。本次让网页保留已核对的字节，不依赖已清理的宿主路径；平台上传、提交与公开仍需分别确认。

## User Stories

- 原成员用既有 Chrome CLI 上传已审核的同一文件，无须绕道注入内存文件或重新制作。
- 页面晚于 CLI 返回才读取文件，字节、文件名和 MIME 仍正确。
- 保留路径/根目录/摘要/大小/变更校验；已知或未知操作都不重复派发。

## Technical Design

继续使用 withUploadFile 创建和核对私有冻结副本，在选择前读成内存 FilePayload，交 Playwright/CDP。由既有 MIME 推断保留文件类型，回执仍仅输出名字、字节数、SHA 与 selected/needsVerification，不输出内容。50MiB 传输上限与现有 admission 不变；临时文件正常清理，不延长整个浏览器的文件暴露时间。

普通直接 Playwright 连接的延迟读取 fixture 未复现；经真实嵌入 CLI 的定向 CDP 路由，在选择返回后再触发 File.arrayBuffer 则稳定复现 NotFoundError。本次将该路径加到真实浏览器回归，而不是用普通连接通过来代替实际 CLI。

## Acceptance

隔离的本地 HTTP 与专用 Chrome，只上传测试字节，不访问账号或投稿。先保留官方旧 CLI 的失败记录，再用候选 CLI 检查选择后的延迟读取、服务端原始 SHA、MIME、未触及的另一页、重复和未知回执不重放。Node/Go 全量与正常提交钩子通过后提 PR；真实运营发布另有平台回执，不能用 fixture 当作发布成功。
