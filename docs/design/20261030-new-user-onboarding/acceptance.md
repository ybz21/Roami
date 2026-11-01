# 第一版设计验收记录

日期：2026-10-30。范围仅为设计文档与独立 HTML；不代表产品功能已实施或真实服务已验证。

## 第二版增补：模块介绍

增加 `module-guide.tsx` 和「认识 Roami」页面，覆盖首页、项目、能力、文件、浏览器、手机、设置七个模块。首页工作台的任务 / 消息 / 记忆、项目中的任务 / 会话 / 工作区，以及能力七类均有用途说明。每项包含使用场景、入口、具体例子和起步建议；不新增完成条件。

- 独立 HTML 重新构建、原型 TypeScript、diff 空白检查通过。
- 模块总览及七项详情，在 320 / 390 / 820 / 1100 / 1280 / 1600 / 1920 共 56 个布局组合下无文档或内容横向溢出；实际 iframe 宽度与 useLayout 档位逐项核对。
- 桌面验证了七个模块入口、能力七类介绍，以及从表单进入介绍再继续设置后，服务地址草稿仍保留。
- 手机尺寸下，详情显示一个返回栏，列表隐藏，顶部标题直接显示模块名称；本轮只做浏览器尺寸检查，没有重新占用共享 Android 真机，不记作新增真机验收。
- [桌面模块介绍](/api/file/tmp/roami-onboarding-v2-modules-desktop.png)、[手机尺寸总览](/api/file/tmp/roami-onboarding-v2-modules-phone.png)、[手机尺寸能力介绍](/api/file/tmp/roami-onboarding-v2-capabilities-phone.png)。手机尺寸截图来自浏览器 iframe，非真机截图。

以下保留第一版验证记录。

## 产物

- `README.md`：产品设计、用户故事、技术设计与后续接入边界。
- `index.html`：单文件交互原型，无 CDN 依赖，无业务 API 请求。
- `prototype.tsx` / `prototype.css` / `build.mjs`：原型源码及可复现构建入口。
- 已加入 `docs/design/README.md` 索引。

工作分支 `feat/new-user-onboarding`，会话名称「新手引导设计」。初始化时工作区干净，执行过 `npm ci` 并安装仓库 Git hooks。

## 已完成的检查

| 检查 | 结果 |
| --- | --- |
| 独立 HTML 构建 | 通过，约 600 KiB |
| 原型源码 TypeScript 检查 | 通过；使用临时 tsconfig 将 React / antd 依赖解析到 frontend/node_modules |
| `scripts/dev/quality/check.sh quick` | 通过；包含 Go tests、前端 i18n / hover / typecheck；按检查器判定跳过无关 Python 检查 |
| 桌面完整模拟流程 | 首页、模型验证并保存、Codex 安装 / 授权返回 / 验证、创建项目、编辑任务、提交回执均走通 |
| 桌面失败场景 | 模型连接失败、Codex 安装失败不显示可用；配置读取失败不显示空安装清单，重试可返回 |
| 部分已配置 | 主模型和一个执行器就绪时，继续设置进入创建项目 |
| 密钥浏览器存储 | sessionStorage 不含填写的 demo-key；只保留非敏感配置状态 |
| 深浅主题 | 两套主题可切换；使用产品 THEME_TOKENS 与 antd 派生主色 |
| 尺寸与溢出 | 320 / 390 / 820 / 1100 / 1280 / 1600 / 1920，各 6 页均无文档 / 内容横向溢出，档位符合 useLayout |
| Android 真触控 | Redmi Note 8 / Android 10 / Chrome 154，约 392 CSS px，coarse 指针；ADB 点按走通主模型、能力接入、创建项目和首个任务 |
| Android 滚动与点击 | 内容区真实滑动，scrollTop 从 0 变为约 158；关键按钮中心与外扩区域通过 elementFromPoint 检查 |
| Android 软键盘 | 检测到约 314 CSS px 键盘，底栏隐藏、输入文字保留。发现发送区遮挡后缩短键盘态输入框并滚入整个 composer；中间版本复验发送区命中成功 |

尺寸检查使用同源 srcdoc iframe，核对每个实际 innerWidth 与 data-size，再逐页读取 scrollWidth / clientWidth。`roami chrome screenshot --viewport` 的尺寸仅对该次截图有效，截图后读取页面不能作为尺寸断言，因此未使用该方法得出上面的 7 档结论。

Android `roami chrome --cdp` 在该设备返回 `CHROME_BROWSER_IDENTITY_UNAVAILABLE`（手机 browser websocket 没有桌面式身份后缀），改用任务专用 CDP 转发读取断言，实际手势仍通过 `roami adb`。未修改 CLI。

键盘布局最终又补充了隐藏任务页次要底部操作的规则。末轮真机复验时设备前台被其他页面占用，因此没有宣称最终 HTML 已完整重跑真机验收；正式产品实现后需重新跑完整手机清单。

## 临时预览证据

以下为本机评审截图，不提交到主干；如后续开 PR，按仓库要求上传 `pr-shots`。

- [桌面主智能体配置](/api/file/tmp/roami-onboarding-desktop-model.png)
- [桌面能力接入](/api/file/tmp/roami-onboarding-desktop-agents.png)
- [桌面项目创建](/api/file/tmp/roami-onboarding-desktop-project.png)
- [手机主智能体配置](/api/file/tmp/roami-onboarding-phone-model.png)
- [手机能力接入](/api/file/tmp/roami-onboarding-phone-agents.png)

## 未实施范围

本版没有真实模型调用、CLI 安装、账号授权、项目写入或任务执行；原型顶部明确标记为演示。配置成功、登录返回和任务回执均为模拟。正式实现还需补齐模型 / 执行器验证契约、节点级进度、全局中英文文案、幂等提交及产品全套验收。

设计原型里的中文属于开发者评审文档，不作为产品 i18n 的例外落入 frontend/src。
