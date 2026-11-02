# 诊断与文档验证记录

日期：2026-11-02。以下记录为早期诊断与设计阶段；随后用户确认实施，最新状态见 [实现与验收记录](implementation.md)。

## 诊断

- 正常登录现有正式服务；分别采样 HTTPS 回环、经环境代理的公网入口、禁用代理的公网入口。
- 禁用代理的完整消息响应：首字节 306.3 ms，总计 43,714.3 ms，4,266,688 B。
- 回环完整消息响应：首字节 213.9 ms，总计 241.5 ms；压缩声明探测未取得 Content-Encoding。
- 托管 Chrome 已登录访问复现消息与任务约 15 秒取消，页面出现连接失败提示。
- 只读 SQLite 核对：16 个登记库均在本地统一根目录；消息、任务、通知源于同一 runtime 库。
- 消息查询命中 branch/seq 索引；task event 查询存在扫描计划；单次状态队列为 0。
- 保留的是脱敏元数据和计时，不保留消息内容、口令、Cookie 或真实会话标识。

完整数值及限制见 [measurements.json](measurements.json)。样本量不足以推断生产 p95。

## HTML 验证

- 桌面 1440 × 1000 CSS 视口打开；目录锚点能定位，正文在 main 中滚动，文档与 body 无横向溢出。
- 计算器在 32、120、1024 KB/s 校验显示与公式：当前传输估算分别约 133.33、35.56、4.17 秒；
  15 秒阈值提示随输入变化。压缩实验和设计预算始终标明来源。
- HTML ID 唯一，内部锚点存在；源码相对链接对应真实文件；内联 JavaScript 通过 node --check。
- HTML 无外部脚本、样式、字体、图片或 CDN 依赖，图形由 CSS 绘制。以项目规范定义配色、字号和间距令牌。
- 中文正文属于开发者设计文档，符合 i18n 文档例外。无产品前端源码改动。

## Android 真机

设备：Redmi Note 8，物理分辨率 1080 × 2340，Chrome 页面宽度约 392 CSS px，DPR 2.75。

- 通过 LAN 静态预览打开文档；实际截图检查首屏、目录、内容留白与计算器。
- ADB 真实点按“实施与验收”，hash 变为 #acceptance，正文滚动到对应段落。
- ADB 真实上滑后 main.scrollTop 从 8731.27 变为 9064.73；document.scrollingElement.scrollTop 仍为 0。
- ADB 点按计算器滑杆后，速率由 120 变为 608 KB/s，当前传输估算变为 7.02 秒，阈值提示相应变化。
- 目录各链接命中高度为 44 CSS px；页面无横向溢出。此处验证的是静态文档，不是尚未实施的产品移动端整改。
- 当前 roami chrome 手机 CDP 入口返回 CHROME_BROWSER_IDENTITY_UNAVAILABLE；真实触控仍使用 roami adb，
  布局和数值断言用本任务文档标签的直接 CDP 补充，不操作其他标签。任务创建的 ADB 转发验证后移除。

## 验证范围与产物

仅修改 docs/design，未提交、发布 PR 或部署，未运行与文档无关的 Go/Python/前端全量运行时门禁。
文档语法、链接、布局和真实触控检查通过；产品实现后的 quick/full、前端门禁、Python 范围检查及性能验收仍需执行。

桌面与真机截图保存在任务临时目录 `/tmp/roami-first-load-20261102/`，未放入 main 的源码目录。
HTML 是自包含文件，停掉临时预览后仍可通过 Roami 文件入口阅读。

## 列表与详情设计补充验证

同日补充了六类对象的字段边界、任务纵向拆表、迁移依赖和专项验收。仅修改设计文档，没有执行 schema 迁移。

- 核对 tasks.list/_view、notifications.list、MemoryCatalog、NativeSessions 与 NativePayloads 源码；
  区分“已有分页但查询整行”和“尚无分页”，没有新增线上性能结论。
- HTML 内部链接、源码链接、ID 唯一性、内联 JavaScript 语法与 git diff --check 通过。
- 桌面查看新增段落并截图；Android 真机打开新增段落、实际滑动，无文档横向溢出，正文仍在 main 滚动。
- 为直接打开文档片段补齐初始锚点定位，避免手机恢复到旧的滚动位置。
- 截图：临时目录中的 list-detail-desktop.png、list-detail-phone.png；ADB 转发和静态预览验证后清理。

## 滚动触发分页设计补充验证

同日补充 scroll-loading 章节：首次一页、顶部回看/底部续读、下拉刷新边界、单游标单请求、
停止条件、页缓存与请求量验收。覆盖主对话、任务/通知/记忆、执行历史和长目录；仍为设计，未实现或宣称请求量已降低。

- 核对 useAgentHistory：entries.slice 仅分批展示已有数据；核对 NativeSession 与 MemoryList 的现有请求入口，
  避免把本地渲染窗口误写成服务端分页，或把已有分页写成全量接口。
- 文档 ID、相对链接、内部锚点、内联脚本语法与 git diff --check 通过。
- 桌面定位新增章节并截图；Android 真机定位后实际滑动，main.scrollTop 从约 7797.09 变为 8117.45，
  bodyScroll 保持 0，无文档横向溢出。
- 宽对照表在自身容器横向滚动，避免手机列宽被压成逐字换行；真实 ADB 横滑并结合 CDP 检查。
- 截图为临时目录中的 scroll-loading-desktop.png、scroll-loading-phone.png；任务创建的预览和转发验证后清理。
