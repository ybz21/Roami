# 手机上装 Roami

Roami 是自托管的，没有商店里的 App。手机端就是这个网站本身，三条路：

| 手机 | 怎么装 | 推送 |
|---|---|---|
| iPhone | Safari 打开 → 分享 → 加到主屏幕 | 加到主屏后才有（iOS 16.4+） |
| Android | Chrome 打开 → 菜单 → 安装应用 | 装完就有 |
| Android（真 App） | 部署者用 `scripts/build/build-apk.sh --install` 打包，手机上「装到手机」页直接下载 | App 自己的长连接，不依赖 Google |

前两条的推送是 Web Push，密钥在 `~/.roami/push/vapid.json`，每个部署自己生成，不经过任何中心服务；
第三条是 App 前台服务挂一条 WebSocket 到 `/api/events/ws`（Gotify / ntfy 的做法），事件来了弹本地通知，通知栏上直接 允许 / 拒绝。

## 一步到位：`#/install`

手机浏览器打开 Roami 的地址、登录，底栏「我」› 「装到手机」，按三步做完即可：装根证书 → 加到主屏 → 开推送。
电脑上 设置 › 关于 › 「装到手机」也能打开同一页，它只会提示你在手机上开这个地址。

## 证书

Roami 默认用自签证书。手机不认它的话，浏览器不把这里当安全网站，推送、麦克风、加到主屏全都没有。

- 安卓：下载 `/cert.crt`，设置 › 安全 › 加密与凭据 › 安装证书 › CA 证书。
- iPhone：Safari 下载 `/cert.crt`，设置 › 已下载描述文件 › 安装，再到 通用 › 关于本机 › 证书信任设置 打开。
- 自己有正式证书：覆盖 `~/.roami/tls/` 下的 `cert.pem` 与 `key.pem` 后重启，`#/install` 页就不再引导装证书。

手机怎么连到 Roami 所在的机器（内网 / VPN / 隧道）不在 Roami 的范围内，和桌面浏览器是同一个前提。

## Android App（mobile/android）

打开先选环境或输网址（摇一摇随时回来），里面通过 WebView 加载同一个 React 站点；网页更新后 App 界面也会更新，
无需重新打包。App 额外处理自签证书信任、文件上传和下载、按需请求麦克风权限，
并用前台服务长连接接收通知，可在通知栏直接允许或拒绝。

```bash
# 需要 JDK 17+、Android SDK（ANDROID_HOME、ANDROID_SDK_ROOT 或常见安装目录；platforms;android-35、build-tools;35.0.0）
scripts/build/build-apk.sh --install
```

`--install` 把包放到 `~/.roami/roami.apk`，Roami 从 `/api/apk` 下发，手机浏览器登录后 我 › 装到手机 就有「下载 apk」。
旧版 App 不支持应用内下载：点首页的更新提示会复制安装页地址，请在手机系统浏览器打开、登录后下载新版。
没有 Google 服务的手机也能收通知；iPhone 没有这条路（iOS 不让 App 后台常驻连接），走上面的加到主屏。

### 桌面角标

原生 App 图标名为「Roami」。它的角标按当前待确认会话和待收尾任务更新；桌面小组件的「待处理」数字使用同一口径。
如果桌面放的是 Chrome 创建的「Roam」网页快捷方式，原生 App 的通知不会显示在那个图标上；请从应用列表把「Roami」添加到主屏幕。
角标还需要开启系统的「通知圆点」以及桌面启动器的通知读取权限。角标颜色和是否显示数字由手机启动器决定。

## 离线

Service Worker 会留一份通知记录、会话总览、项目列表和最近打开过的对话记录。断网时打开这些页面看到的是上次同步的内容，
底栏上方会有一条黄色提示。终端本身需要在线。
