# 模型源目录内编辑已添加模型

## Product Design

已添加模型行保留状态与防重复选择行为，新增常显“编辑”按钮，复用现有模型编辑表单。保存或返回均回到原模型源页面，保留未提交的目录选择、手动输入及连接草稿。同一个上游模型对应多个本地模型时，分别提供带名称的编辑入口。

## User Stories

我在已拉取的模型源目录中发现名称、模型 ID 或聚合策略需要修正时，可以直接编辑并返回继续添加模型，无需重新拉取或重复填写。

## Technical Design

`ModelSourceEditor` 按已保存候选项关联模型，通过 `onEditModel` 进入 `ModelHub` 的既有 URL 编辑页。`ModelHub` 记录本次编辑的来源，保存与取消使用同一返回逻辑；各模型源草稿继续由原状态所有者保存。按钮复用 `.tt-act`，布局使用既有间距令牌，中英可访问名称包含模型名称，粗指针命中高度沿用 44px 规则。

## Acceptance

- `ModelHub.test.tsx` 验证目录内进入编辑、更新名称和上游模型 ID、稳定本地 ID、保留来源凭据、保存后回到模型源且目录选择与手动输入保留；无需再次拉取。该文件 15 项通过。
- 桌面真实隔离服务：拉取本地测试目录，编辑保存名称后自动回到原页面；中文深色与英文浅色均显示可访问的编辑入口，无横向溢出。
- Redmi Note 8（1080×2340，DPR 2.75）：通过 LAN HTTPS 访问隔离服务，使用 `roami adb` 实际点按编辑、输入名称及保存，回到原 URL 后名称已更新。`elementFromPoint` 命中编辑按钮，按钮高度 44 CSS px；`data-size=compact`、`data-pointer=coarse`；仅一个二级返回栏，底部四入口保留。真实滑动后内容滚动位置从 0 增至 378.91，文档滚动保持 0，视口宽度与文档宽度均为 392，无横向溢出。
- 手机 Chrome 的 `roami chrome --cdp` 返回 `CHROME_BROWSER_IDENTITY_UNAVAILABLE`，因此手机交互全部使用 `roami adb`，通过同一转发 CDP 只读核对 DOM 和布局。桌面交互使用 `roami chrome`。
- 截图位于 `/tmp/roami-409-editor-desktop.png`、`/tmp/roami-409-editor-desktop-en-light.png`、`/tmp/roami-409-editor-phone.png`，不提交一次性图片。
- 使用私有 tmux 和独立数据目录运行验收实例；只读本地模型目录，不执行付费推理，不修改现用模型连接。
- 最终 `scripts/dev/quality/check.sh full` 通过：Go 全量测试、前端 typecheck / i18n / hover、生产构建及秘密扫描。前端全量 Vitest 167 个文件、1,220 项通过。保留已有的大 chunk 构建提示；Python 因无相关改动按范围跳过。已清理本任务的服务、测试目录上游、浏览器标签、ADB 转发和私有 tmux。
