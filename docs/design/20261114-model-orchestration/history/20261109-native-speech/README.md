# 原生成员的语音审计入口

## Product Design

原数据成员能用现有 Node 登录转写用户指定的最终音轨，不需要匿名调用或手工处理凭据。文本来自既有语音服务；转写成功不是内容审核通过，更不是发布成功。Main 读取原始响应与实际文件摘要后独立决定。

## User Stories

- 使用 `roami speech transcribe --file FILE.wav --file-root ROOT --expected-file-sha256 SHA --json`，沿用现有服务、登录与 TLS CA。
- 输入不匹配或超范围时不发请求；401 提示重新登录，失败和未知不自动重试。
- 审计保留最终 MP4、其原始音轨副本及派生 WAV 的来源、转换命令、字节与 SHA。不能用原始 TTS 文件替代最终成片音轨。

## Technical Design

CLI 复用 `apiConnection` 的已保存 cookie、服务发现、TLS 验证和拒绝重定向策略，仅调用现有 `/api/speech/transcribe`。不新增服务器鉴权旁路，不开放任意 HTTP 代理，不接受 provider/model/凭据参数，不改变配置、环境或费用记录。

本地先验证明确的根目录、已存在常规 WAV、25 MiB 上限与预期 SHA，再发送一次 multipart `audio`。使用实际读取的同一份字节，防止校验后重新打开不同文件。WAV 由最终成片音轨解码生成，转换作为证据，原 MP4 和编码流副本不改动。CLI 返回转写与原始 HTTP 响应、输入摘要，响应只保留安全的状态/内容类型，不输出认证信息。超时不自动重发。

此变更仅增加 CLI，Web/Python、语音配置与模型参数不变。交付时可单独更新 CLI，无需为音轨审计重启正在执行的服务或原成员；组件版本分别记录。

## Acceptance

真实缺口：原数据成员 r25 匿名 HTTP 返回401，`roami auth status` 同时为 authed=true。隔离验证使用既有保存 cookie、精确音频上传与响应留存，覆盖401不重放和本地校验先于网络。最终还需原数据成员的实际 ASR响应与 Main 审阅；不能以本 CLI 的夹具转写当生产验收。
