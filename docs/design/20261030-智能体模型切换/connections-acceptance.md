# 连接与模型合并验收

2026-10-31。用户指出模型与模型源分成两页；本轮将它们合并为按连接分组的模型管理。

## 产品与保存行为

- 模型、用量与限额、模型定价三个页签；连接及其模型在同一列表相邻展示。
- 添加连接时同一表单填写地址、协议、凭据及多个模型；已有连接可直接添加模型。
- 一次确认、一次目录提交。保留原路由 ID、已有密钥、主备策略和备用候选，不迁移数据库。
- 保存后连接和模型保持列表位置；失败保留草稿。原生预设引用仍由现有后端保护。
- 旧模型源列表和详情链接可继续打开，智能体管理入口进入同一模型列表。

## 自动化

- 前端覆盖合并列表与旧链接、连接和两个模型一次确认提交、编辑时保留路由与主备候选、原有定价和智能体选择回归。
- typecheck、i18n、hover、生产构建和 quick 质量门通过；完整 Vitest 为 153 个文件、1132 项测试通过。

## 桌面与 Android

隔离实例 `/tmp/roami-model-connections-run`，使用虚构模型服务和测试密钥；所有原生 CLI 配置位于隔离目录，不改用户模型选择。

Redmi Note 8，1080×2340、DPR 2.75。ADB 实际点按连接编辑、上下滑动表单、模型 ID 输入、保存与确认。软键盘弹出后 `--kb=314px`，正在输入的模型字段可见；收起后可触达保存。保存后的目录回读保留密钥和原路由 ID，模型值更新；最终复验确认按钮为 44px，连接及模型顺序不变；`scrollWidth=innerWidth=392`，文档 scrollTop=0。顶栏和底部四个主入口保持一致。

桌面中英文界面均检查。真实浏览器一次新增连接与 demo-model-a / demo-model-b，目录回读为一条新连接、两个新模型，已有连接未覆盖。

## 产物

- [合并后的桌面列表](/api/file/tmp/model-connections-desktop.png)
- [合并后的手机列表](/api/file/tmp/model-connections-phone.png)
- [同一表单配置连接与模型（桌面）](/api/file/tmp/model-connections-editor-desktop.png)
- [手机模型编辑](/api/file/tmp/model-connections-editor-phone.png)
- [手机键盘输入](/api/file/tmp/model-connections-keyboard-phone.png)

隔离实例通过同一 launcher 停止，移除本任务的手机调试转发；用户真实 CLI 配置和线上实例未被此轮验收修改。
