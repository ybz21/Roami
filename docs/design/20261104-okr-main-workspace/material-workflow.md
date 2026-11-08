# 可读物料目录与既有发布流程

## Product Design

物料按日期、渠道和简短主题查找，执行身份留在清单。新产物使用
`materials/YYYY-MM-DD/<channel-or-work-type>/<short-topic>/`；日 README 列出
真实文件与状态。修改保留文件版本，不为每次执行再生成一层 UID 目录。

沿用旧目录的在途任务继续原交付位置，历史和已发布证据不搬迁。索引直接链接
原件，避免复制素材增加另一套事实。个人长期记忆仍按稳定成员身份管理。

## User Stories

- 用户从日期与主题直接打开正文、图片和视频，无需辨认任务或运行 ID。
- 成员沿用原任务和会话，新一轮使用可读物料路径，清单保留完整 task/revision/run。
- Main 先检查项目已验证的发布方式，区分当前限制、缺失连接与真实操作失败。
- 临时只读验收结束后，运营遵循用户实际持续授权；明确的设备限制仍需核对范围。

## Technical Design

本次修改 canonical `skills/okr-development` 的根与内层 AGENTS、相关手册和
authoring/bundle/Connector 约定。新增模板 `assets/materials/README.md` 作为物料入口，
`assets/.roami/okr/manuals/publishing.md` 记录项目实际选用的通道与恢复步骤。
既有 `package.files` 覆盖完整初始化包，保持复制 `assets/.` 即可初始化的协议。

目录布局不是执行身份：宿主继续核对真实项目、成员、task/revision/run、清单、文件
字节和 SHA。新路径不删除身份检查、不更改任务或发布状态，也不使复制件自动成为
新运行成果。既有账号、设备、遗忘与停止边界保留，不能从模板获得执行许可。

已有成功的手机、网页或 API 工作流可作为项目发布流程。API/MCP 目录为空不能证明
所有发布方式不可用；新接口开发也不自动废止原流程。Main 按实际错误处理，参数
错误不改称账号拒绝，制作验收、发布指派、平台公开与 Connector 数据分别留证。

## 验证范围

初始化包 frontmatter 校验通过；完整 assets 含隐藏文件复制通过；74 个 package
manifest 哈希逐一匹配。真实项目已对齐可读目录约定并提供链接原件的物料入口，
保留在途任务路径与历史。实际发布需要继续核对用户设备边界与真实账号状态；
这些文档和初始化验证不代表完成了发布循环。
