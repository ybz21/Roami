---
name: ttmux
description: >
  使用 ttmux 将复杂任务拆分为多个并行子任务，通过 tmux 会话管理执行。
  支持普通命令并行和多 Claude Agent 编排两种模式。
user-invocable: true
allowed-tools:
  - Bash(ttmux *)
  - Bash(cat ~/.local/share/ttmux/logs/*)
  - Bash(cat ~/.local/share/ttmux/agents/*)
  - Bash(python3 *)
  - Read
  - Write
  - Edit
---

# /ttmux — 任务拆分与多 Agent 编排

你可以使用 `ttmux`（位于 `~/.local/bin/ttmux`）进行任务拆分和并行执行。

参数: `$ARGUMENTS`

## 什么时候该用

- 用户的任务可以拆成 2 个以上独立子任务并行执行
- 需要同时启动多个 Claude 实例各自完成不同工作
- 长时间运行的命令需要在后台执行并监控
- CI 类场景：lint + test + build 同时跑

## 核心能力

ttmux 有两套编排模式：

### 模式一：命令并行（spawn）

适合跑 shell 命令，如构建、测试、脚本等。

### 模式二：多 Agent（agent）

适合将一个大任务拆给多个 Claude 实例并行完成。每个 Agent 是一个独立的
Claude Code 进程（`claude -p --dangerously-skip-permissions`），运行在
独立的 tmux 会话中，有自己的上下文和工具权限。

## 环境变量

ttmux 支持全局环境变量，所有新建的 session 自动继承：

```bash
# 设置代理（通常已配好，先检查）
roami session env

# 如需设置
roami session env set https_proxy=http://127.0.0.1:7890
roami session env set http_proxy=http://127.0.0.1:7890
```

**重要：启动 Agent 前先 `roami session env` 确认代理等环境变量已设好。**

## 任务拆分原则

收到用户任务后，按以下步骤拆分：

1. **识别独立性** — 哪些子任务之间没有依赖？可以同时做的就并行
2. **控制粒度** — 每个子任务是一个清晰、可独立完成的工作单元
3. **命名清晰** — 用简短英文小写：`auth-api`、`login-ui`、`db-migration`
4. **不超过 6 个** — 并行太多反而低效，通常 2~4 个最佳
5. **定义边界** — 明确每个 Agent 负责哪些文件，**禁止 Agent 之间改同一个文件**

## 工作流：多 Agent 编排

### 第一步：拆分任务

分析用户需求，识别可并行的子任务。拆分时确保：
- 每个子任务操作不同的文件/模块
- 子任务之间无依赖关系
- 组装步骤由你（主 Claude）来做，不交给子 Agent

### 第二步：启动 Agent 组

```bash
roami session agent spawn <组名> \
  "<任务1名>" "<任务1详细描述>" \
  "<任务2名>" "<任务2详细描述>" \
  "<任务3名>" "<任务3详细描述>" \
  --dir <工作目录>
```

默认权限是 `dangerously-skip-permissions`（子 Agent 可自由读写文件、执行命令）。
如需限制权限，用 `--perm plan`（只规划不执行）或 `--perm auto`。

可用选项：
- `--dir <目录>` — Agent 工作目录（默认当前目录）
- `--model <模型>` — 指定模型（如 sonnet、opus）
- `--perm <模式>` — 权限模式（默认 dangerously-skip-permissions）
- `--max-turns <N>` — 最大轮次限制

### 第三步：等待并监控

```bash
# 每隔一段时间检查状态
roami session agent status <组名>
```

状态含义：
- **运行中 [bash]** — claude 进程正在执行
- **完成 (exit 0)** — 成功完成
- **失败 (exit N)** — 执行出错
- **已结束 (日志可用)** — 进程已退出，可查日志

**轮询策略**：首次等 30 秒，之后每 15 秒查一次，直到全部完成或超时。

### 第四步：收集结果

```bash
roami session agent collect <组名>          # 人类可读
roami session agent collect <组名> --json   # 结构化输出
```

### 第五步：验证

这一步至关重要！收集完结果后必须验证：

1. **检查文件是否存在** — `ls` 确认所有预期文件
2. **检查内容正确性** — `cat` 或 `Read` 检查关键函数/结构
3. **运行测试** — 如果有测试就跑，没有就手动验证
4. **修复问题** — 如果某个 Agent 的产出有问题，可以：
   - 自己直接修复（优先）
   - 用 `roami session agent send <会话名> "修复指令"` 让 Agent 修

### 第六步：组装

子 Agent 产出独立模块后，由你来完成组装：
- 创建入口文件 / 整合模块
- 运行完整的集成验证
- 向用户汇报结果

### 第七步：清理

```bash
roami session agent kill <组名>
```

**必须清理**，不要留下孤立会话。

## 任务描述编写规范

子 Agent 收到的是一段纯文本任务描述，它会用 `claude -p` 模式执行。
描述必须足够具体：

### 必须包含

1. **角色** — "你是一个 Python/TypeScript/... 开发者"
2. **目标文件** — 精确到文件路径：`在 /path/to/file.py 中实现...`
3. **具体内容** — 列出要实现的函数/类/接口
4. **边界约束** — "只写这一个文件，不要修改其他文件"

### 好的任务描述

```
你是一个Python开发者。在 /tmp/project/math_utils.py 中实现以下3个函数：
1) is_prime(n) 判断是否为素数，返回bool
2) fibonacci(n) 返回第n个斐波那契数(fib(0)=0, fib(1)=1, fib(10)=55)
3) gcd(a, b) 返回最大公约数
只写这一个文件，不要写其他文件。
```

### 差的任务描述

```
写点数学工具函数
```

## 工作流：命令并行

适合跑 shell 命令（非 Claude 任务）：

```bash
roami session spawn build \
  "lint"  "npm run lint" \
  "test"  "npm test" \
  "types" "npx tsc --noEmit"

roami session wait build --timeout 120
roami session collect build
roami session group kill build
```

## 模式三：蜂群编排（swarm）

当一摊活需要**有目标、能被持续监护、成员间有依赖**时，用蜂群。
蜂群 = 一个有目标的任务组（成员可以是命令任务，也可以是 Claude Agent，二者共存），
并且可以**交给 cc-swarm（神）接管监护**。

```bash
# 1. 建蜂群（带目标）
roami session swarm new login --goal "给项目加登录功能：注册/登录/JWT"

# 2. 加成员（agent 或 task；可声明依赖）
roami session swarm add login api   --type agent --dir ~/proj "实现登录/注册 API"
roami session swarm add login ui    --type agent --dir ~/proj "实现登录页面"
roami session swarm add login e2e   --type task  --depends-on api,ui "npm run e2e"

# 3. 看状态 / 收集
roami session swarm ls
roami session swarm status login
roami session swarm collect login

# 4. 交给 cc 监护（自动拉起一个交互式指挥会话 cc-login，作用域只盯这个蜂群）
roami session swarm adopt login          # 或 --by <已有cc会话> 复用现有指挥

# 5. 收尾
roami session swarm done login           # 标记完成（不杀会话）
roami session swarm archive login        # 杀会话、留元数据
roami session swarm rm login             # 彻底删除
```

**何时用蜂群 vs spawn/agent**：
- 一次性并行小活、跑完即弃 → `spawn` / `spawn --agent`（轻量）。
- 有明确目标、要持续监护到交付、成员有先后依赖、想让 cc 接管 → `swarm`（重量、闭环）。

`swarm adopt` 会把蜂群交给 cc-swarm，指挥会话用 `/cc-swarm --swarm <名>` 进入**作用域巡检**，
只监护该蜂群的成员（而非全局所有 `cc-*`）。详见 cc-swarm skill。

## 参数分发

当用户通过 `/ttmux` 调用时：

- **无参数** → `roami session status`，汇报当前状态
- **`run <描述>`** → 分析任务、拆分、启动 Agent 组、监控、收集、组装、验证
- **`swarm <描述>`** → 建蜂群、加成员、（可选）`swarm adopt` 交给 cc 监护
- **`check <组名>`** → 查看状态
- **`collect <组名>`** → 收集并汇总
- **`clean`** → 清理所有 Agent 组
- **其他** → 转发给 ttmux

## 完整示例

用户说："写一个 Python 工具包，包含字符串、数学、文件操作三个模块"

你应该：

```bash
# 1. 确认环境
roami session env

# 2. 启动 3 个 Agent
roami session agent spawn minitools \
  "string" "你是一个Python开发者。在 /tmp/project/string_utils.py 中实现 reverse(s), count_vowels(s), to_snake_case(s) 三个函数。只写这一个文件。" \
  "math"   "你是一个Python开发者。在 /tmp/project/math_utils.py 中实现 is_prime(n), fibonacci(n), gcd(a,b) 三个函数。只写这一个文件。" \
  "file"   "你是一个Python开发者。在 /tmp/project/file_utils.py 中实现 read_lines(path), word_count(path), find_files(dir,pattern) 三个函数。只写这一个文件。" \
  --dir /tmp/project

# 3. 等待（首次等 30s）
sleep 30
roami session agent status minitools

# 4. 状态还是运行中就继续等
sleep 15
roami session agent status minitools

# 5. 全部完成后收集
roami session agent collect minitools

# 6. 验证文件
ls /tmp/project/*.py

# 7. 自己写 main.py 组装
# （用 Write 工具创建 main.py，import 三个模块）

# 8. 运行验证
python3 /tmp/project/main.py

# 9. 清理
roami session agent kill minitools

# 10. 向用户汇报
```

## 规则

1. **先检查环境** — 启动前 `roami session env` 确认代理配好，`roami session ls` 检查无同名会话
2. **先收集再清理** — 永远 collect → kill，顺序不能反
3. **最多 6 个 Agent** — 并行太多反而慢
4. **文件不能冲突** — 每个 Agent 操作自己的文件，绝不交叉
5. **必须验证** — 收集后一定要检查文件存在、内容正确、能运行
6. **组装是你的活** — 子 Agent 写模块，你来整合
7. **失败先看日志** — `roami session capture <会话名>` 或 `cat ~/.local/share/ttmux/logs/<会话名>.log`
8. **必须清理** — 完成后 `roami session agent kill <组名>`
9. **汇报要完整** — 向用户说明每个子任务的结果，不遗漏
