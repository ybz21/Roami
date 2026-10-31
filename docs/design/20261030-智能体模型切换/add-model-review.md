# 简化添加模型：原型验收

2026-10-31。对应 [产品提案](add-model-design.md) 和 [交互稿](add-model.html)。本轮仅设计文档与静态原型；不发送真实模型请求，不保存真实密钥，不修改运行中的网关或智能体配置。

## 桌面

通过真实浏览器操作及运行时断言验证：

1. 默认只有地址、密钥两个主输入，连接选项折叠。
2. 搜索不会丢失已选模型。
3. 多选后一次加入来源及模型。
4. 选项卡依次为模型、定价、聚合策略、用量与限额。
5. 已有来源直接进入选择页，已添加模型不可重复选择。
6. 添加第二个来源后，原来源及其模型仍保留。
7. 保存失败保留密钥、勾选，不留下半个来源。
8. 保存失败后重试可完成。
9. 无目录时手动多行添加，对重复名称去重。

所有九项断言通过。JavaScript 语法检查通过。原型的失败、目录与保存结果均为明确标记的演示状态；不是后端发现接口的集成测试。

## Android 真机

Redmi Note 8，设备 `216d6a43`，1080×2340、DPR 2.75，CSS 宽 392。通过独立 HTTPS 静态测试实例访问。

- 用 ADB 真实点按、输入示例地址与密钥；读取后真实勾选两个模型，添加结果为两个模型。
- 模型行高 56px；选项卡命中区至少 44×44px。
- ADB 上滑后内容 scrollTop 从 0 到约 42.55，文档 scrollTop 始终为 0；scrollWidth=392，与视口一致。
- 实际切换定价、聚合策略；定价保留缓存读写字段，策略显示备用入口。
- 搜索键盘弹出后隐藏底部导航，主按钮上移。结合 VirtualKeyboard 边界，并为输入法候选栏留一档空间；最终按钮底边约 415.82 CSS px，实际在键盘上方可见。
- 键盘打开时直接用 ADB 点“添加 1 个模型”，成功进入结果页，原已有模型和新增模型共两个。

Roami Chrome CLI 对手机端返回 `CHROME_BROWSER_IDENTITY_UNAVAILABLE`，手机改用 ADB 实际操作并通过只读 CDP 核对状态。没有把 DOM `.click()` 当成手机触控验收。

## 证据

- [打开交互稿（HTML）](/api/file/tmp/roami-model-add-design/index.html)
- [两个主输入（桌面）](/api/file/tmp/roami-model-add-design/add-desktop.png)
- [勾选多个模型（桌面）](/api/file/tmp/roami-model-add-design/select-desktop.png)
- [填写连接（手机）](/api/file/tmp/roami-model-add-design/add-phone.png)
- [勾选多个模型（手机）](/api/file/tmp/roami-model-add-design/select-phone.png)
- [键盘打开时的添加按钮（手机）](/api/file/tmp/roami-model-add-design/keyboard-phone.png)
- [独立聚合策略页（手机）](/api/file/tmp/roami-model-add-design/strategy-phone.png)

静态测试实例和本轮手机转发在验收后清理；可交互 HTML 和截图单独保留。未将一次性截图加入仓库，也未将原型接入产品路由或部署。
