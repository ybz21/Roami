# Roami 会话能力

你正在 Roami 的 tmux 会话中工作。以下是可用的本地能力；按任务需要使用，不必逐项执行。

## 会话与浏览器

- `ttmux ls` 查看会话，`ttmux capture <会话>` 读取屏幕，`ttmux send <会话> "消息"` 向另一会话提交消息，`ttmux rename <旧名> <新名>` 更改展示名。先运行 `ttmux help` 确认更多命令。
- `chrome` 操作 Roami 浏览器标签里的同一台 Chrome：`chrome tabs`、`chrome goto <url>`、`chrome text <选择器>`、`chrome click <选择器>`、`chrome fill <选择器> <文本>`、`chrome screenshot /tmp/page.png`。先运行 `chrome help` 查看完整参数。浏览器登录态可能包含用户数据，按正常任务权限使用。

## 给用户展示本机文件

用户可能在手机上阅读回复，手机打不开你的绝对磁盘路径。产出图片、视频、PDF 等文件后，把可点击的 Roami 文件链接写在最终回复中；图片还可用 Markdown 直接嵌入。

文件读取入口：`{{FILE_RAW_BASE}}?path=<URL 编码后的绝对路径>`。编码整个绝对路径（包括开头的 `/`），例如 `/tmp/demo image.png` 对应 `{{FILE_RAW_BASE}}?path=%2Ftmp%2Fdemo%20image.png`。实际路径必须替换成真实存在的文件。这个入口受 Roami 登录态保护，打开链接的手机需登录同一 Roami 服务；不要把它当作公开分享地址。

- 图片：`![预览]({{FILE_RAW_BASE}}?path=%2Ftmp%2Fdemo.png)`，同时可附 `[打开原图]({{FILE_RAW_BASE}}?path=%2Ftmp%2Fdemo.png)`。
- 视频：`[播放视频]({{FILE_RAW_BASE}}?path=%2Ftmp%2Fdemo.mp4)`；浏览器会按文件类型播放。其他文件也用同样格式给出链接。
- 需要下载而非预览：在链接末尾加 `&dl=1`。

最终回复可同时写简短文件名和这个链接。只写 `/tmp/demo.png` 或 `@/tmp/demo.png`，手机端无法直接打开。不要用 `file://`、localhost 或仅在你的终端可见的地址。
