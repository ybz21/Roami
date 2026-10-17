# plugins/ — 插件统一目录

所有插件都住在这里，**每个插件一个目录；builtin 插件共用根 Go module**（或一个插件包）。

```
plugins/
  im/                # IM 机器人(飞书已支持,钉钉等可扩展;常驻 concierge 管家)
  reviewmesh/        # 智能互审(空闲自动互审、意见回灌)
  examples/
    hello-py/        # exec 运行时示例插件(Python,插件包形态)
      roam-plugin.json
      main.py
```

## 两种形态

| | **builtin Go 插件** | **插件包** |
| --- | --- | --- |
| 例子 | `im`、`reviewmesh` | `examples/hello-py`、第三方 |
| 运行时 | 编译进 roami 二进制 | node / exec 子进程 |
| 分发 | 随 Roam 一起，默认启用 | 走 `roami plugin install` 安装，默认不启用 |
| 语言 | Go | 任意可执行（Node、Python…） |
| 何时用 | 官方/核心能力，要开箱即用 | 第三方、快速迭代、非 Go 语言 |

---

## 如何开发插件

### 第一步：选形态
- 想做**官方/核心**能力、能用 Go、希望随 Roam 开箱即用 → **路径 A（builtin Go）**。
- 想**快速迭代**、用非 Go 语言、或做**第三方**分发 → **路径 B（插件包）**。

### 路径 A：builtin Go 插件
builtin 插件与宿主共用根 Go module，**manifest 与实现同住插件包、init() 自注册**，宿主代码零手改。新增一个：

1. 建目录 `plugins/<名>/`，不要另建 `go.mod`。
2. 只依赖公开 SDK `github.com/ybz21/Roami/pkg/plugin/sdk` 与 `github.com/ybz21/Roami/pkg/plugin/manifest`，**不碰宿主 internal**。
3. 包里写 `register.go` 自注册（manifest 声明也在这里）：

   ```go
   func init() { sdk.RegisterBuiltin(Manifest(), Activate) }
   ```

4. 跑 `bash scripts/dev/gen-builtin-plugins.sh`：扫 `plugins/` 目录自动生成 blank-import 接线
   （`internal/plugin/builtin/imports_gen.go`）。
5. 从根目录运行 `go build ./cmd/roami`，重新构建安装 roami 才生效（builtin 编译期链接，不热更）。

> 参考实现：`plugins/hostmonitor`（主机监控，最小样例）、`plugins/cron`（定时任务，常驻调度循环样例）、`plugins/im`（IM 桥 + provider 适配 + 常驻 concierge）、`plugins/reviewmesh`。

> Go 插件也可以**不进 builtin、按地址注册**：加个 `main.go` 调 `sdk.Serve(Activate)` 编译成独立二进制，
> 配一份 `roam-plugin.json`（`runtime.kind=exec`），`roami plugin install <目录>` 即注册，
> Roam 负责拉起子进程与生命周期——协议与 builtin 完全相同，宿主与 cli 一行不用改。

### 路径 B：插件包（node/exec）
manifest 驱动，走安装流程，不用改宿主代码：

```sh
roami plugin dev init my-plugin        # 脚手架(roam-plugin.json + src/ + schema)
cd my-plugin
roami plugin dev validate .            # 校验 manifest(schema + 引用文件)
roami plugin dev run . -- greet        # 不安装,开发模式直接拉起并调命令
roami plugin install .                 # 装到 $ROAMI_HOME/plugins/installed/<id>/<version>/
roami plugin enable my.plugin          # 安装后默认不启用
roami plugin run my.plugin.greet
roami plugin logs my.plugin --follow   # 看插件 stderr 日志
```

最小 `roam-plugin.json`（完整字段见 [05-manifest.md](../docs/design/plugin/05-manifest.md)）：

```json
{
  "manifestVersion": 1,
  "id": "acme.hello", "publisher": "acme", "name": "hello", "version": "0.1.0",
  "displayName": { "zh-CN": "你好插件", "en-US": "Hello Plugin" },
  "engines": { "roam": ">=0.6.0" },
  "main": "dist/main.js",
  "runtime": { "kind": "node", "activation": "lazy" },
  "permissions": {},
  "activationEvents": ["onCommand:acme.hello.greet"],
  "contributes": { "commands": [{ "id": "acme.hello.greet", "title": { "zh-CN": "打招呼", "en-US": "Greet" } }] }
}
```

### 通用规范（两种形态都适用）
- **只走平台 API**：不要直接碰 tmux / sqlite / claude 命令行，一切经 `ctx` 上的平台 API（[06-platform-api.md](../docs/design/plugin/06-platform-api.md)）——否则没有权限记录/审计，review 会拒。
- **不写前端**：设置界面由宿主按 config schema 自动渲染。
- **常驻靠 watchers，别自己 `setInterval`**：声明 `watchers`，由宿主调度/持久化/恢复；进程空闲会被回收（约 10 分钟后 deactivate）。
- **handler 要幂等**：事件是「至少一次」投递；跨激活要保存的状态放 `ctx.storage`。
- **最小权限**：`permissions` 只声明真正需要的。

### 更多
- 完整开发指南（从 hello 到发布）：[09-plugin-development.md](../docs/design/plugin/09-plugin-development.md)
- 机制主文档 / 架构 / 安全模型：[docs/design/plugin/](../docs/design/plugin/)（[README](../docs/design/plugin/README.md) · [04-architecture](../docs/design/plugin/04-architecture.md) · [07-security](../docs/design/plugin/07-security.md)）
