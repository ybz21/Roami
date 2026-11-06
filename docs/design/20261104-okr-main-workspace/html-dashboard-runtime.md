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

Main 的页面上下文也带上真实 htmlDashboardSupported/teamRoleBindings 和已确认 team；OkrMainChat 根据能力生成内部编写说明。新宿主说明 schema2/html 与资产先准备后保存，旧宿主继续限制 schema1/widgets；不能在支持HTML的宿主仍告诉Main只支持旧组件。未确认的发送重试继续保留原幂等载荷和原Main，不借能力更新创建替身。专项覆盖两类宿主及原职责绑定。

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
- 最终前端202文件1472项通过，typecheck、5192 key i18n、hover、build通过。Go全量、正常quick/full、Python运行时及四组Skill检查通过；Skill包专项3项另过。最后仅补验收文档，内部Main提示与分包代码均在full覆盖的源码中。

不触用户手机；粗指针模拟不计真机验收。不替换原项目Main/成员，不触模型路由、账目或busy。公开截图仅使用此fixture。

### 带鉴权的实际项目副本

将真实确认定义/25条观测/2次复盘复制到隔离目录，再由真实Go发布器确认7指标HTML草稿，非看板定义及成员绑定均不变。独立浏览器context使用合成HttpOnly/SameSite=Lax cookie：无cookie401，受保护iframe文档收到cookie并正常握手；子页仍读不到Cookie/父DOM。7张卡实际显示11、5、2及4项未知，无数据时不画零线。没有使用生产凭据或改真实项目。证据 /tmp/okr-html-dashboard-auth-qa-20261106/acceptance.json。

普通图表包的生产构建前后均516452B；HTML专用脚本1122085B独立动态加载，不进入普通图表依赖。只证明加载/传输边界，不宣称CPU或内存降低。证据 /tmp/okr-html-dashboard-chunk-proof-20261106.json。

### 原Main、原成员与口径纠正

真实项目通过roami chrome让原Main续派原数据成员的原任务至第7轮；实例、原生对话/分支、任务和native session五类身份均保留。成员回群后Main读取实际文件并受管验收。独立复核发现报告虽数值正确，却把同日规则写成capturedAt最大；Main保留原件、CAS追加记忆更正，再续派第8轮纠正。修正版的10份输入哈希、7项事实和全部逐日末条/追加索引已独立复核，Main再执行受管验收并更新日索引。

这证明原实例可以追加任务、群聊交付后唤起Main、记忆保留旧文并明确纠正；投递、执行器完成、Main验收与独立复核是不同证据。该轮未新增观测、未启用HTML、未发布或开日程。材料在 /tmp/okr-project-html-draft-20261106/。

### 全屏 Main 的可见性边界

后续线上粗指针模拟发现：compact/medium 打开Main次级页面时，Data页签仍为选中，不能仅按页签判断iframe可见。ProjectOkr现在同时判断Main是否覆盖工作区：覆盖时传active=false，移除iframe/通道；关闭后恢复确认快照。large双栏中看板仍可见，保留iframe，不干扰Main或任务。专项先在compact/medium复现、large通过，修正后三档及原页面/通道专项23项通过；未操作真机。
