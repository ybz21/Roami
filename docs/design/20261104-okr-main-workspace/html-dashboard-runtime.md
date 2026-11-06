# 项目 HTML 看板运行态

## 产品设计

数据看板只显示项目自定义视图，不增加配置页。完整模板先复制 assets，再选择 HTML manifest。项目 Main 使用现有保存/同步操作确认；设计、数据绑定和 Connector Skill 属于项目目录。编辑 HTML 不改变已确认版本。

## 用户故事

- 与 Main 讨论指标和布局，由 Main 修改 dashboard/ 的 HTML/CSS/JS，不要求用户学习 React。
- 每个子表/指标有自己的数字、趋势或表格卡片，按需使用已有 ECharts。
- Connector 通过 collect/record 确认真实数据，所有卡片读取同一快照；未知不变成零。
- 保留项目和页签导航，离开看板释放通道。失败只有一个重试入口。

## 技术设计

### 文件与确认

schemaVersion=1 保留 widgets；schemaVersion=2 使用 html {entry, assets, metricIds, libraries?}，widgets=[]。资产限定 dashboard/ 内 UTF-8 html/css/js，最多32个、每个1 MiB、总计2 MiB。保存/同步前文件必须存在。清单和绑定一起校验，网页不能指定其他项目。

backend/okr/dashboard-html.go 捕获文件并检查路径、符号链接、大小和哈希，保存 state/dashboard-assets/<digest>.json。confirmedSnapshot 引用内容摘要；观测/复盘推进版本仍引用原资产，避免重复复制和草稿自动上线。dashboard-markup.go 在服务器解析 HTML，将相对脚本/样式改写成 data URL，先注入 dashboard-sdk.js。非法文件不会替换确认快照。

GET /projects/:key/okr/dashboard 返回绑定与摘要；GET .../dashboard/document?digest=<摘要>&nonce=<32hex> 只返回当前确认文档，旧摘要409。均使用原鉴权路由且禁止缓存。文档响应头和 iframe 均限制 sandbox，仅 allow-scripts，无 allow-same-origin。

### 只读数据桥

OkrHtmlDashboard.tsx 按 node/project/digest 创建 MessageChannel。首次 load 向 opaque iframe 转交 port；之后只单向推送声明指标、语言/主题/尺寸/令牌，以及按声明懒加载的本地 ECharts。父页面不提供 RPC、文件、写入、项目切换或凭据。read/subscribe 访问内存副本并复制返回数据。

ProjectOkr 的现有共享30秒刷新提供 workspace，不增加逐卡 HTTP 轮询。切换项目/节点/摘要取消旧请求；页签离开、document hidden 或卸载关闭 port 并移除 iframe。返回时对齐当前配置；文档第二次 load 也关闭通道。超时/加载错误提供重试。

dashboard-datasets.ts 沿用来源身份过滤和同日追加顺序。latest=null 表示未知，0为真实值；points 为每日最后观测。quality仅 observed/unknown，lastError=null不代表采集健康。workspace尚无持久失败/时效状态，不伪造 stale/error；源失败保留旧事实。

### 模板与组件

使用语义 HTML 卡片/表格和项目令牌，等待 okr.ready() 再读数据或使用 echarts，退出时销毁订阅和图表。parts/dashboard/html/dashboard.json 是可选覆盖；完整 assets 包含 AGENTS.md、OKR、Connector Skill、团队、记忆及禁用计划。清单、HTML与okr.json的指标ID一致。检查 htmlDashboardSupported 后才启用，旧宿主继续schema1。

### 边界

拒绝远程资源、嵌套frame、form、refresh meta和越界路径。CSP限制 fetch/socket、远程脚本、表单与worker；不能保证任意JS的完整网络/CPU隔离，脚本仍可能自导航。只加载经过确认的项目代码，数据流不能有密钥。强敌对代码隔离需要独立域/进程。

依据：[MDN iframe sandbox](https://developer.mozilla.org/en-US/docs/Web/HTML/Reference/Elements/iframe)、[MessageChannel](https://developer.mozilla.org/en-US/docs/Web/API/Channel_Messaging_API/Using_channel_messaging)、[CSP](https://developer.mozilla.org/en-US/docs/Web/HTTP/Reference/Headers/Content-Security-Policy)。

## 验收记录

证据保存 /tmp/okr-html-dashboard-ui-20261106。隔离 fixture 使用真实 Go文件发布/API、ProjectOkr/OkrHtmlDashboard、opaque iframe与本地ECharts6.1.0。

- roami chrome 操作 OKR/数据页签，确认离开时移除 iframe、返回重建通道。
- 1280/1920/2560/3440宽度及390 compact均无文档/iframe横向溢出，iframe有可用高度；另建390 coarse上下文验证 pointer=coarse。
- 浏览器内验证 parent DOM、document.cookie 和未声明指标均不可读，真实ECharts画布存在。
- 新增真实 fixture 观测0→7、revision3→4，页面原有共享刷新推送到现存HTML；未增加逐卡HTTP请求。资产重新确认推进到revision5仍保留3条事实。
- 专项覆盖未确认文件不执行、非法发布保留旧确认、越界/远程资源/符号链接、文件篡改、错误project/digest、旧异步响应、隐藏/离开释放与再次load关闭。
- 前端202文件1470项通过，typecheck、5192 key i18n、hover、build通过。Go OKR/API整包通过，Skill包专项3项通过。正式quick/full及PR待完成。

不触用户手机；粗指针模拟不计真机验收。不替换原项目Main/成员，不触模型路由、账目或busy。公开截图仅使用此fixture。
