# 浏览器本机文件上传验收

2026-11-04。范围为浏览器 CLI、原生 browser_act 的参数与工作区边界；未改 Swarm 调度、registry、模型路由或取消协议。

## 实际执行

专用临时 profile 的 headless Chrome，经 CDP 执行文件选择；仅向本机 HTTP fixture 发送 multipart。独立构建的 `roami` 也通过内嵌 launcher/driver 执行同一上传。测试读取现有 MP4 后复制到 fixture 的临时文件，不修改原素材。

```sh
scripts/dev/isolated-roami.sh /tmp/roami-browser-upload-quality \
  env -u ROAM_HOME GOMAXPROCS=2 GOFLAGS=-p=1 \
  go build -o /tmp/roami-browser-upload ./cmd/roami

ROAMI_BROWSER_UPLOAD_ACCEPTANCE=1 \
ROAMI_PLAYWRIGHT_MODULE=/absolute/node_modules/playwright-core/index.mjs \
ROAMI_TEST_ROAMI_BIN=/tmp/roami-browser-upload \
ROAMI_UPLOAD_ACCEPTANCE_FILE=/absolute/source.mp4 \
ROAMI_UPLOAD_ACCEPTANCE_SCREENSHOT=/tmp/browser-upload-acceptance.png \
node --test backend/browser/automation/file-upload-browser.test.mjs
```

2026-11-04 本机实际通过：服务端接收 **1,844,211 bytes**，SHA256 为 `af0cb43c95b10640bf2e987b4a8b01398419dd9bd1e330b0acaa78062f2ea97c`，与源素材一致。另一个 target 的 input.files 长度保持 0。三次服务端接收分别属于正常选择、选择后模拟丢失应答、内嵌 CLI 三个不同操作；重复原 operation ID 没有第四次上传。CLI operation-status 返回原成功回执；模拟丢应答的回执为 unknown/outcomeKnown=false，未再次派发。场景不符、非文件输入框均在选择前拒绝。

执行日志 `/tmp/browser-upload-cli-acceptance.log`；截图 `/tmp/browser-upload-acceptance.png` 为临时验收产物，不提交到 main。临时 HTTP 服务、Chrome/profile 和私有 CLI daemon 由 fixture 清理，不连接用户 Chrome。

最初裸 Chrome fixture 在文件选择之前发生导航超时。采用 Playwright 常用的测试启动选项关闭专用实例的后台网络、组件更新与媒体路由等后台功能后通过；截图前仅激活专用 fixture 标签。没有改全局代理、Chrome 配置或人的标签。

## 原生任务调用

```json
{
  "kind": "upload",
  "selector": "input[type=file]",
  "path": "/absolute/prepared-task-workspace/artifacts/video.mp4",
  "sha256": "af0cb43c95b10640bf2e987b4a8b01398419dd9bd1e330b0acaa78062f2ea97c",
  "observationId": "id-from-browser-observe"
}
```

kind、selector 和 path 必需，sha256 可选。完整工具 schema 接受 observationId；紧凑模型 schema 省略它时，只从同一 turn 已交付的任务观察解析，可用 resourceId 限定。继续复用既有 task/run/turn/lease/scene 和持久 operation ID。

文件必须位于 **binding.workspace.directory** 内；项目原始路径只有在该项目目录就是准备好的任务工作区时才可直接使用，否则先将素材放入已授权任务工作区。Python 拒绝无工作区、相对路径和词法越界；Node 再校验真实文件根、拒绝末级 symlink 与父 symlink 越界，实际打开可读普通文件，创建私有快照并校验摘要后才输入。

成功返回 `action: {operationId,state:"succeeded",selected:true,file:{name,sizeBytes,sha256}}` 和 `needsVerification:true`，以及新的观察；这只证明文件已选入页面。当前 CDP 传输要求小于 50 MiB，超限在输入前返回 `CHROME_UPLOAD_TRANSPORT_LIMIT_EXCEEDED`，并非平台大小限制。`capabilities.fileUpload` 明示 `{maxBytes:52428799,limitSource:"playwright-cdp",confirmation:"selected"}`；现有文件大小配置可进一步收窄。

控制面 `GET /api/agent/tasks/:taskId/resources` 的 actions 继续给出 `id/resourceId/taskId/runId/state/inputStopped/outcomeKnown/errorCode/createdMs/updatedMs`；完整选择元数据随 driver output 持久化在 resource_actions.result_json。unknown 仍阻止后续输入；只查询已有回执和观察当前页面，不能换 ID 盲重试。

## 专业 CLI 边界

```sh
roami chrome upload 'input[type=file]' /absolute/workspace/video.mp4 \
  --target STABLE_TARGET_ID --expected-browser BROWSER_ID \
  --expected-scene SCENE_SHA256 --file-root /absolute/workspace \
  --expected-file-sha256 FILE_SHA256 --operation-id STABLE_32_HEX \
  --receipt-root PRIVATE_DIRECTORY --no-focus --no-retry --no-start
roami chrome operation-status --operation-id STABLE_32_HEX --receipt-root PRIVATE_DIRECTORY
```

回执 `result.stdout` 是 `{selected:true,needsVerification:true,file:{name,sizeBytes,sha256}}` 的 JSON 字符串。上传命令本身始终仅派发一次，不自动启动替代 Chrome，不回落其他标签。显式 operation ID 可持久恢复同一调用；没有 ID 的原始 CLI 没有跨调用去重保证。

专业能力桥接的 `--context/--call` 当前不接纳 builtin browser；原始 chrome CLI 不能冒称已有该绑定。专业成员可以执行现有终端 CLI，但平台强制任务/运行归属需要单独的专业浏览器桥接。此次未扩大该范围。原生入口已绑定工作区与资源租约，优先用于受管投稿任务。

## 检查与限制

定向 Node 测试 33 通过；Python 浏览器、公开 CLI、上传边界定向 57 通过，其中新增上传路径/schema 9 项。新增 Node 文件测试覆盖不可读、空/缺失/目录、symlink 越界、摘要不符、大小上限、私有快照清理及 unknown 不重放。统一 quick/full 结果随提交交接补充。

这不是 Bili/X 发布验收：未登录任何平台，未触手机或用户浏览器，未部署。页面自动传输完成、平台提交回执、发布状态和可公开查看需要后续实际受管任务分别核验。
