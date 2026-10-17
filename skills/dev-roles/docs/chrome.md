# chrome（CLI）· 浏览器自动化详解

`chrome` 是浏览器自动化 CLI（Playwright over CDP），驱动 ttmux Web 镜像的那台 Chrome。
**验收 Web 类成果时用它真跑一遍**（开页面、点按钮、断言文本），比只读代码可靠。

## 命令

```bash
roami chrome setup                       # 安装/更新依赖 (node + playwright-core)，首次用一次
roami chrome goto <url>                  # 打开网址
roami chrome click <选择器>              # 点击
roami chrome fill  <选择器> <文本>       # 填表单（直接设值）
chrome type  <选择器> <文本>       # 逐字键入
roami chrome press [选择器] <键>         # 按键，如 Enter / Control+a
roami chrome text  [选择器]              # 取可见文本（默认 body）——断言常用
chrome html  [选择器]              # 取 HTML（默认整页）
chrome attr  <选择器> <属性>       # 取属性值
roami chrome eval  "<js>"               # 页面内执行 JS 并打印返回(JSON)
roami chrome wait  <选择器>              # 等元素出现
roami chrome screenshot [文件] [--full]  # 截图（默认 screenshot.png）
chrome pdf   [文件]                # 导出 PDF (headless)
roami chrome tabs                        # 列标签页（序号 / 标题 / url）
roami chrome new   [url]                 # 新开标签页
roami chrome close                       # 关闭标签页
roami chrome help                        # 完整用法
```

## 选项

- 通用：`--tab <序号>` | `--url <子串>` 选目标标签页（默认第一个）；`--timeout <ms>`（默认 15000）；`--cdp <地址>`。
- 截图：`--viewport 1280x800` `--wait <ms>` `--clip x,y,w,h` `--fast` `--quality <1-100>`(jpg)；
  `--fresh --goto <url>` 用临时干净 Chrome 截图；`--mobile` / `--device iphone|iphone-se|pixel|ipad` 指定机型。
- 环境：`TTMUX_CHROME_CDP=http://127.0.0.1:9222`，`TTMUX_CHROME_SCALE=2`。

## 验收套路（qa / frontend / fullstack 必用）

```bash
roami chrome goto "http://127.0.0.1:<端口>/<页面>"
roami chrome wait "#app"                       # 等渲染
roami chrome text ".result"                    # 取文本，对照预期断言
roami chrome click "button.submit"             # 模拟交互
roami chrome text ".toast"                     # 断言交互后的反馈
roami chrome screenshot /tmp/check.png --full  # 留证据 / 人工复核
```

- 断言要**对照验收标准**逐条跑（正常 / 边界 / 异常路径都点一遍），别只截一张图就说"看起来对"。
- 发现不符 → 广场 `swarm say --kind block --re <卡> "<现象+复现步骤>"` @负责人，别自己改实现（除非你就是负责人）。
