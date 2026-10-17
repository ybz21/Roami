# 审批 (approve)

审批是最高优先级的操作 — session 卡在审批就完全停摆了。

## 审批类型

Claude Code 的交互式审批有几种：

### 文件操作
```
Do you want to create foo.py?
❯ 1. Yes
  2. Yes, allow all edits during this session
  3. No
```
**判断要点**：文件名和路径合理吗？是不是在预期的目录下？

### 命令执行
```
Bash command
  cd /path && npm test
Do you want to proceed?
❯ 1. Yes
  2. No
```
**判断要点**：命令安全吗？有没有 `rm -rf`、`git push --force`、`DROP TABLE` 等危险操作？

### 目录/文件访问
```
Do you want to allow access to /some/path?
❯ 1. Yes
  2. Yes, and always allow
  3. No
```
**判断要点**：路径合理吗？是项目内还是系统目录？

## 决策逻辑

```
读 capture 输出
  ↓
识别出审批提示
  ↓
理解它要做什么
  ↓
判断是否安全合理
  ├── 安全 → tmux send-keys -t <session> Enter
  ├── 不确定 → 读更多上下文再判断
  └── 危险 → 不批，通知用户
```

## 批准方式

```bash
tmux send-keys -t <session> Enter
```

Enter 键选择默认选项（通常是 Yes）。

## 危险操作 — 不自动批

以下操作即使看起来合理也**不自动批**，等用户确认：

- `rm -rf` 删除目录
- `git push --force` / `git reset --hard`
- `DROP TABLE` / `DELETE FROM` 无 WHERE
- 修改 `.env`、credentials、secrets
- `kill -9` 系统进程
- 写入 `/etc/`、`/usr/` 等系统路径

## 批量审批

如果一个 session 连续出现很多审批（比如创建多个文件），可以考虑选 option 2（"Yes, allow all edits during this session"）来一次性放行：

```bash
# 发送 "2" 选择第二个选项
tmux send-keys -t <session> 2
```

但只在确认 session 的工作方向正确时才这样做。

## 非审批类阻塞

除了权限审批，session 还会被其他提示卡住：

### 评分提示
```
How is Claude doing this session? (optional)
  1: Bad    2: Fine   3: Good   0: Dismiss
```
直接发 `0` dismiss：
```bash
tmux send-keys -t <session> 0
```

### 待发命令
prompt `❯` 后有文字但没按 Enter。这通常是：
- 上一轮 `roami session send` 发过去了但因为 session 在审批状态没处理
- 用户手动输入了但忘了按回车

判断文字内容合理后：
```bash
tmux send-keys -t <session> Enter
```
